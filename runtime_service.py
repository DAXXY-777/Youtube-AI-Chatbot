"""Small settings, cooldown, and activity service shared by the UI and Nightbot API."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from threading import RLock
from urllib.parse import parse_qs, urlparse

from sqlalchemy import delete, exists, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from database import Database, database
from logging_config import get_logger, log_event
from model_presets import PRESET_MODELS
from network_safety import validate_cloud_base_url
from orm_models import NightbotRequest, RuntimeConfiguration, StreamContext, Viewer, utc_now
from secret_store import SecretStore, WindowsCredentialStore


LOCAL_MODE = "local"
CLOUD_MODE = "cloud"
VIEWER_COOLDOWN = timedelta(minutes=1)
DATABASE_RETRY_SECONDS = 30.0
NO_STREAM_PATTERN = re.compile(r"^No stream (\d+)$")
YOUTUBE_WATCH_HOST = "www.youtube.com"
YOUTUBE_VIDEO_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{6,}$")
logger = get_logger("runtime")


@dataclass(frozen=True)
class ViewerIdentity:
    identity_key: str
    provider: str | None
    provider_id: str | None
    username: str | None
    display_name: str | None
    user_level: str | None

    @property
    def label(self) -> str:
        return self.display_name or self.username or "anonymous"


@dataclass(frozen=True)
class RuntimeSettings:
    active_mode: str
    local_preset_label: str
    cloud_base_url: str | None
    cloud_model_id: str | None
    cloud_api_key_configured: bool
    active_stream_url: str | None
    active_context_label: str
    temporary_memory_mode: bool


@dataclass(frozen=True)
class RequestContext:
    mode: str
    stream_context_id: int
    stream_label: str
    stream_url: str | None
    local_preset_label: str
    cloud_base_url: str | None
    cloud_model_id: str | None
    cloud_ready: bool


@dataclass(frozen=True)
class ActivityEntry:
    id: int
    received_at: str
    viewer: str
    prompt: str
    response: str
    mode: str


@dataclass
class _MemoryRuntimeState:
    active_mode: str = LOCAL_MODE
    local_preset_label: str = PRESET_MODELS[0].label
    cloud_base_url: str | None = None
    cloud_model_id: str | None = None
    cloud_api_key_configured: bool = False
    active_stream_url: str | None = None


class RuntimeService:
    """Persist settings when possible, with an in-memory fallback for core replies."""

    def __init__(self, app_database: Database, secret_store: SecretStore) -> None:
        self.database = app_database
        self.secret_store = secret_store
        self._startup_no_stream_context_id: int | None = None
        self._initialization_lock = RLock()
        self._cooldown_lock = RLock()
        self._initialized = False
        self._temporary_memory_mode = False
        self._temporary_state = _MemoryRuntimeState()
        self._memory_cooldowns: dict[str, datetime] = {}
        self._next_database_retry_at = 0.0

    def initialize(self) -> None:
        """Initialize SQLite once, falling back to an in-memory session if it is unavailable."""
        with self._initialization_lock:
            if self._initialized:
                return
            try:
                pruned_count, label = self._initialize_database()
            except (OSError, SQLAlchemyError) as error:
                self._activate_temporary_memory_mode(error)
                label = "Temporary memory mode"
                pruned_count = 0
            self._initialized = True
            log_event(
                logger,
                "runtime_initialized",
                no_stream_context=label,
                pruned_requests=pruned_count,
                temporary_memory_mode=self._temporary_memory_mode,
            )

    def get_settings(self) -> RuntimeSettings:
        if not self._database_available():
            return self._temporary_settings()
        try:
            with self.database.session_factory() as session:
                configuration = self._configuration(session)
                context = self._active_context(session, configuration)
                settings = self._settings_from(configuration, context, temporary=False)
        except (OSError, SQLAlchemyError) as error:
            self._activate_temporary_memory_mode(error)
            return self._temporary_settings()
        self._remember_settings(settings)
        return settings

    def get_request_context(self) -> RequestContext:
        if not self._database_available():
            return self._temporary_request_context()
        try:
            with self.database.session_factory() as session:
                configuration = self._configuration(session)
                stream = self._active_context(session, configuration)
                context = RequestContext(
                    mode=configuration.active_mode,
                    stream_context_id=stream.id,
                    stream_label=stream.label,
                    stream_url=stream.youtube_url if stream.kind == "youtube" else None,
                    local_preset_label=configuration.local_preset_label,
                    cloud_base_url=configuration.cloud_base_url,
                    cloud_model_id=configuration.cloud_model_id,
                    cloud_ready=self._cloud_ready(
                        configuration.cloud_base_url, configuration.cloud_model_id
                    ),
                )
        except (OSError, SQLAlchemyError) as error:
            self._activate_temporary_memory_mode(error)
            return self._temporary_request_context()
        self._remember_request_context(context)
        return context

    def runtime_status(self) -> str:
        context = self.get_request_context()
        if context.mode == LOCAL_MODE:
            from model_runtime import local_model_runtime

            status = local_model_runtime.status_for(context.local_preset_label)
        else:
            status = (
                "Cloud provider configured"
                if context.cloud_ready
                else "Cloud provider not configured"
            )
        if self._temporary_memory_mode:
            return f"Temporary memory mode | {status}"
        return status

    def save_mode(self, mode: str) -> RuntimeSettings:
        normalized = mode.strip().lower()
        if normalized not in {LOCAL_MODE, CLOUD_MODE}:
            raise ValueError("Choose Local or Cloud mode.")
        if not self._database_available():
            self._temporary_state.active_mode = normalized
            return self._temporary_settings()
        try:
            with self.database.session_factory() as session:
                configuration = self._configuration(session)
                configuration.active_mode = normalized
                session.commit()
                settings = self._settings_from(
                    configuration, self._active_context(session, configuration), temporary=False
                )
        except (OSError, SQLAlchemyError) as error:
            self._activate_temporary_memory_mode(error)
            self._temporary_state.active_mode = normalized
            return self._temporary_settings()
        self._remember_settings(settings)
        log_event(logger, "mode_saved", mode=normalized)
        return settings

    def save_local_settings(self, preset_label: str) -> RuntimeSettings:
        if preset_label not in {preset.label for preset in PRESET_MODELS}:
            raise ValueError("Choose a listed local model.")
        if not self._database_available():
            self._temporary_state.local_preset_label = preset_label
            return self._temporary_settings()
        try:
            with self.database.session_factory() as session:
                configuration = self._configuration(session)
                configuration.local_preset_label = preset_label
                session.commit()
                settings = self._settings_from(
                    configuration, self._active_context(session, configuration), temporary=False
                )
        except (OSError, SQLAlchemyError) as error:
            self._activate_temporary_memory_mode(error)
            self._temporary_state.local_preset_label = preset_label
            return self._temporary_settings()
        self._remember_settings(settings)
        log_event(logger, "local_model_selected", preset=preset_label)
        return settings

    def save_cloud_settings(
        self, base_url: str, api_key: str, model_id: str
    ) -> RuntimeSettings:
        """Validate first so a failed edit never overwrites working Cloud settings."""
        normalized_url = self._normalize_cloud_url(base_url)
        normalized_model_id = model_id.strip() or None
        supplied_key = api_key.strip()

        if not normalized_url or not normalized_model_id:
            raise ValueError("Enter both the Cloud API URL and model ID.")
        if not supplied_key and not self.secret_store.get_cloud_api_key():
            raise ValueError("Enter a Cloud API key before saving the first Cloud setup.")

        if supplied_key:
            self.secret_store.set_cloud_api_key(supplied_key)

        if not self._database_available():
            self._temporary_state.cloud_base_url = normalized_url
            self._temporary_state.cloud_model_id = normalized_model_id
            if supplied_key:
                self._temporary_state.cloud_api_key_configured = True
            return self._temporary_settings()
        try:
            with self.database.session_factory() as session:
                configuration = self._configuration(session)
                configuration.cloud_base_url = normalized_url
                configuration.cloud_model_id = normalized_model_id
                if supplied_key:
                    configuration.cloud_api_key_configured = True
                session.commit()
                settings = self._settings_from(
                    configuration, self._active_context(session, configuration), temporary=False
                )
        except (OSError, SQLAlchemyError) as error:
            self._activate_temporary_memory_mode(error)
            self._temporary_state.cloud_base_url = normalized_url
            self._temporary_state.cloud_model_id = normalized_model_id
            if supplied_key:
                self._temporary_state.cloud_api_key_configured = True
            return self._temporary_settings()
        self._remember_settings(settings)
        log_event(
            logger,
            "cloud_settings_saved",
            base_url_configured=bool(normalized_url),
            model_configured=bool(normalized_model_id),
            api_key_supplied=bool(supplied_key),
        )
        return settings

    def set_active_stream(self, raw_url: str) -> RuntimeSettings:
        youtube_url = raw_url.strip()
        if youtube_url:
            self._validate_youtube_watch_url(youtube_url)
        if not self._database_available():
            self._temporary_state.active_stream_url = youtube_url or None
            return self._temporary_settings()
        try:
            with self.database.session_factory() as session:
                configuration = self._configuration(session)
                if not youtube_url:
                    configuration.active_stream_id = None
                else:
                    stream = self._find_or_create_youtube_context(session, youtube_url)
                    configuration.active_stream_id = stream.id
                session.commit()
                settings = self._settings_from(
                    configuration, self._active_context(session, configuration), temporary=False
                )
        except (OSError, SQLAlchemyError) as error:
            self._activate_temporary_memory_mode(error)
            self._temporary_state.active_stream_url = youtube_url or None
            return self._temporary_settings()
        self._remember_settings(settings)
        log_event(logger, "stream_context_saved", youtube_stream_active=bool(youtube_url))
        return settings

    def claim_viewer_cooldown(self, viewer_identity: ViewerIdentity) -> bool:
        """Atomically reserve a viewer's one-minute request window before inference."""
        now = utc_now()
        with self._cooldown_lock:
            self._discard_expired_memory_cooldowns(now)
            expires_at = self._memory_cooldowns.get(viewer_identity.identity_key)
            if expires_at is not None and expires_at > now:
                return False

            if self._database_available():
                try:
                    with self.database.session_factory() as session:
                        viewer = session.scalar(
                            select(Viewer).where(
                                Viewer.identity_key == viewer_identity.identity_key
                            )
                        )
                        if viewer is not None and self._within_cooldown(
                            viewer.last_seen_at, now
                        ):
                            return False
                        self._upsert_viewer(session, viewer_identity, last_seen_at=now)
                        session.commit()
                except (OSError, SQLAlchemyError) as error:
                    self._activate_temporary_memory_mode(error)

            self._memory_cooldowns[viewer_identity.identity_key] = now + VIEWER_COOLDOWN
            return True

    def record_request(
        self,
        request_context: RequestContext,
        viewer_identity: ViewerIdentity,
        prompt: str,
        response: str,
    ) -> int | None:
        """Persist activity when possible; a write failure must not invalidate the reply."""
        if not self._database_available() or request_context.stream_context_id < 1:
            return None
        try:
            with self.database.session_factory() as session:
                configuration = self._configuration(session)
                self._prune_expired_data(
                    session,
                    configuration,
                    preserve_context_id=request_context.stream_context_id,
                )
                viewer = self._upsert_viewer(session, viewer_identity, touch_last_seen=False)
                request = NightbotRequest(
                    viewer_id=viewer.id,
                    stream_context_id=request_context.stream_context_id,
                    mode=request_context.mode,
                    prompt=prompt.strip()[:1500],
                    response=response.strip()[:400],
                )
                session.add(request)
                session.commit()
                return request.id
        except (OSError, SQLAlchemyError) as error:
            self._activate_temporary_memory_mode(error)
            log_event(logger, "activity_record_failed", error_type=type(error).__name__)
            return None

    def list_activity(self, limit: int = 100) -> tuple[str, list[ActivityEntry]]:
        if not self._database_available():
            return "Temporary memory mode", []
        try:
            with self.database.session_factory() as session:
                configuration = self._configuration(session)
                context = self._active_context(session, configuration)
                rows = session.execute(
                    select(NightbotRequest, Viewer)
                    .join(Viewer, NightbotRequest.viewer_id == Viewer.id)
                    .where(NightbotRequest.stream_context_id == context.id)
                    .order_by(NightbotRequest.received_at.desc(), NightbotRequest.id.desc())
                    .limit(limit)
                ).all()
                entries = [
                    ActivityEntry(
                        id=request.id,
                        received_at=request.received_at.isoformat(),
                        viewer=viewer.display_name or viewer.username or "anonymous",
                        prompt=request.prompt,
                        response=request.response,
                        mode=request.mode,
                    )
                    for request, viewer in reversed(rows)
                ]
                return context.label, entries
        except (OSError, SQLAlchemyError) as error:
            self._activate_temporary_memory_mode(error)
            return "Temporary memory mode", []

    def _initialize_database(self) -> tuple[int, str]:
        self.database.initialize()
        with self.database.session_factory() as session:
            configuration = self._configuration(session)
            no_stream = self._create_next_no_stream_context(session)
            self._startup_no_stream_context_id = no_stream.id
            if configuration.active_stream_id is not None:
                stream = session.get(StreamContext, configuration.active_stream_id)
                if stream is None or stream.kind != "youtube":
                    configuration.active_stream_id = None
            pruned_count = self._prune_expired_data(session, configuration)
            session.commit()
            settings = self._settings_from(
                configuration, self._active_context(session, configuration), temporary=False
            )
        self._temporary_memory_mode = False
        self._remember_settings(settings)
        return pruned_count, no_stream.label

    def _database_available(self) -> bool:
        if not self._temporary_memory_mode:
            return True
        if time.monotonic() < self._next_database_retry_at:
            return False
        with self._initialization_lock:
            if not self._temporary_memory_mode:
                return True
            if time.monotonic() < self._next_database_retry_at:
                return False
            try:
                self._initialize_database()
            except (OSError, SQLAlchemyError) as error:
                self._activate_temporary_memory_mode(error)
                return False
            log_event(logger, "database_persistence_restored")
            return True

    def _activate_temporary_memory_mode(self, error: Exception) -> None:
        self._temporary_memory_mode = True
        self._next_database_retry_at = time.monotonic() + DATABASE_RETRY_SECONDS
        log_event(logger, "database_temporarily_unavailable", error_type=type(error).__name__)

    @staticmethod
    def _configuration(session: Session) -> RuntimeConfiguration:
        configuration = session.get(RuntimeConfiguration, 1)
        if configuration is None:
            configuration = RuntimeConfiguration(id=1)
            session.add(configuration)
            session.flush()
        return configuration

    def _active_context(
        self, session: Session, configuration: RuntimeConfiguration
    ) -> StreamContext:
        if configuration.active_stream_id is not None:
            stream = session.get(StreamContext, configuration.active_stream_id)
            if stream is not None and stream.kind == "youtube":
                return stream
        if self._startup_no_stream_context_id is None:
            raise RuntimeError("Runtime service has not been initialized.")
        stream = session.get(StreamContext, self._startup_no_stream_context_id)
        if stream is None:
            raise RuntimeError("Current No stream context is unavailable.")
        return stream

    @staticmethod
    def _create_next_no_stream_context(session: Session) -> StreamContext:
        labels = session.scalars(
            select(StreamContext.label).where(StreamContext.kind == "no_stream")
        ).all()
        numbers = [
            int(match.group(1))
            for label in labels
            if (match := NO_STREAM_PATTERN.match(label)) is not None
        ]
        context = StreamContext(
            kind="no_stream", label=f"No stream {max(numbers, default=0) + 1}"
        )
        session.add(context)
        session.flush()
        return context

    @staticmethod
    def _find_or_create_youtube_context(session: Session, youtube_url: str) -> StreamContext:
        stream = session.scalar(
            select(StreamContext).where(StreamContext.youtube_url == youtube_url)
        )
        if stream is None:
            stream = StreamContext(
                kind="youtube", label=youtube_url, youtube_url=youtube_url
            )
            session.add(stream)
            session.flush()
        return stream

    @staticmethod
    def _upsert_viewer(
        session: Session,
        identity: ViewerIdentity,
        *,
        last_seen_at: datetime | None = None,
        touch_last_seen: bool = True,
    ) -> Viewer:
        viewer = session.scalar(
            select(Viewer).where(Viewer.identity_key == identity.identity_key)
        )
        if viewer is None:
            viewer = Viewer(
                identity_key=identity.identity_key,
                provider=identity.provider,
                provider_id=identity.provider_id,
                username=identity.username,
                display_name=identity.display_name,
                user_level=identity.user_level,
                last_seen_at=last_seen_at or utc_now(),
            )
            session.add(viewer)
            session.flush()
        else:
            viewer.provider = identity.provider or viewer.provider
            viewer.provider_id = identity.provider_id or viewer.provider_id
            viewer.username = identity.username or viewer.username
            viewer.display_name = identity.display_name or viewer.display_name
            viewer.user_level = identity.user_level or viewer.user_level
            if touch_last_seen:
                viewer.last_seen_at = last_seen_at or utc_now()
        return viewer

    def _prune_expired_data(
        self,
        session: Session,
        configuration: RuntimeConfiguration,
        *,
        preserve_context_id: int | None = None,
    ) -> int:
        cutoff = utc_now() - timedelta(days=30)
        result = session.execute(
            delete(NightbotRequest).where(NightbotRequest.received_at < cutoff)
        )
        request_exists_for_viewer = exists(
            select(NightbotRequest.id).where(NightbotRequest.viewer_id == Viewer.id)
        )
        # A viewer can be inside a model call before its first request record
        # exists. Retain that cooldown marker until normal expiry rather than
        # making a restart immediately bypass the one-minute limit.
        session.execute(
            delete(Viewer).where(
                ~request_exists_for_viewer,
                Viewer.last_seen_at < cutoff,
            )
        )

        protected_context_ids = [
            context_id
            for context_id in (
                configuration.active_stream_id,
                self._startup_no_stream_context_id,
                preserve_context_id,
            )
            if context_id is not None
        ]
        request_exists_for_context = exists(
            select(NightbotRequest.id).where(
                NightbotRequest.stream_context_id == StreamContext.id
            )
        )
        stale_contexts = delete(StreamContext).where(~request_exists_for_context)
        if protected_context_ids:
            stale_contexts = stale_contexts.where(
                StreamContext.id.not_in(protected_context_ids)
            )
        session.execute(stale_contexts)
        return int(result.rowcount or 0)

    @staticmethod
    def _within_cooldown(last_seen_at: datetime, now: datetime) -> bool:
        if last_seen_at.tzinfo is None:
            last_seen_at = last_seen_at.replace(tzinfo=UTC)
        return now - last_seen_at < VIEWER_COOLDOWN

    def _temporary_settings(self) -> RuntimeSettings:
        return RuntimeSettings(
            active_mode=self._temporary_state.active_mode,
            local_preset_label=self._temporary_state.local_preset_label,
            cloud_base_url=self._temporary_state.cloud_base_url,
            cloud_model_id=self._temporary_state.cloud_model_id,
            cloud_api_key_configured=self._temporary_state.cloud_api_key_configured,
            active_stream_url=self._temporary_state.active_stream_url,
            active_context_label="Temporary memory mode",
            temporary_memory_mode=True,
        )

    def _temporary_request_context(self) -> RequestContext:
        state = self._temporary_state
        return RequestContext(
            mode=state.active_mode,
            stream_context_id=-1,
            stream_label="Temporary memory mode",
            stream_url=state.active_stream_url,
            local_preset_label=state.local_preset_label,
            cloud_base_url=state.cloud_base_url,
            cloud_model_id=state.cloud_model_id,
            cloud_ready=self._cloud_ready(state.cloud_base_url, state.cloud_model_id),
        )

    def _remember_settings(self, settings: RuntimeSettings) -> None:
        self._temporary_state.active_mode = settings.active_mode
        self._temporary_state.local_preset_label = settings.local_preset_label
        self._temporary_state.cloud_base_url = settings.cloud_base_url
        self._temporary_state.cloud_model_id = settings.cloud_model_id
        self._temporary_state.cloud_api_key_configured = settings.cloud_api_key_configured
        self._temporary_state.active_stream_url = settings.active_stream_url

    def _remember_request_context(self, context: RequestContext) -> None:
        self._temporary_state.active_mode = context.mode
        self._temporary_state.local_preset_label = context.local_preset_label
        self._temporary_state.cloud_base_url = context.cloud_base_url
        self._temporary_state.cloud_model_id = context.cloud_model_id
        self._temporary_state.cloud_api_key_configured = context.cloud_ready
        self._temporary_state.active_stream_url = context.stream_url

    @staticmethod
    def _settings_from(
        configuration: RuntimeConfiguration, context: StreamContext, *, temporary: bool
    ) -> RuntimeSettings:
        return RuntimeSettings(
            active_mode=configuration.active_mode,
            local_preset_label=configuration.local_preset_label,
            cloud_base_url=configuration.cloud_base_url,
            cloud_model_id=configuration.cloud_model_id,
            cloud_api_key_configured=configuration.cloud_api_key_configured,
            active_stream_url=context.youtube_url if context.kind == "youtube" else None,
            active_context_label=context.label,
            temporary_memory_mode=temporary,
        )

    def _cloud_ready(self, base_url: str | None, model_id: str | None) -> bool:
        try:
            api_key = self.secret_store.get_cloud_api_key()
        except Exception as error:
            log_event(logger, "cloud_secret_unavailable", error_type=type(error).__name__)
            return False
        return bool(base_url and model_id and api_key)

    def _discard_expired_memory_cooldowns(self, now: datetime) -> None:
        self._memory_cooldowns = {
            identity: expires_at
            for identity, expires_at in self._memory_cooldowns.items()
            if expires_at > now
        }

    @staticmethod
    def _normalize_cloud_url(raw_url: str) -> str | None:
        value = raw_url.strip()
        return validate_cloud_base_url(value) if value else None

    @staticmethod
    def _validate_youtube_watch_url(youtube_url: str) -> None:
        parsed = urlparse(youtube_url)
        video_ids = parse_qs(parsed.query, keep_blank_values=True).get("v", [])
        if (
            parsed.scheme != "https"
            or parsed.netloc.lower() != YOUTUBE_WATCH_HOST
            or parsed.path != "/watch"
            or len(video_ids) != 1
            or not YOUTUBE_VIDEO_ID_PATTERN.fullmatch(video_ids[0])
        ):
            raise ValueError("Paste https://www.youtube.com/watch?v=<video-id>.")


runtime_service = RuntimeService(database, WindowsCredentialStore())
