import pickle
import time
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, Optional

from googleapiclient.discovery import build
from langchain_ollama import OllamaLLM
from langchain_core.prompts import (
    ChatPromptTemplate, 
    HumanMessagePromptTemplate, 
    SystemMessagePromptTemplate
)

class YouTubeBot:
    def __init__(
        self, 
        max_message_length: int = 200, 
        cooldown_duration: int = 30,
        log_level: int = logging.INFO
    ):
        # Configure logging
        logging.basicConfig(
            level=log_level, 
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        self.logger = logging.getLogger(__name__)

        # Load credentials
        try:
            with open('youtube_token.pickle', 'rb') as token:
                credentials = pickle.load(token)
        except Exception as e:
            self.logger.error(f"Failed to load credentials: {e}")
            raise

        # Create YouTube API service
        self.youtube = build('youtube', 'v3', credentials=credentials, cache_discovery=True)
        
        # Configurable parameters
        self.MAX_MESSAGE_LENGTH = max_message_length
        self.COOLDOWN_DURATION = cooldown_duration
        
        # Time-limited cooldown tracking
        self.command_cooldown: Dict[str, float] = {}

    def send_message(self, livechat_id: str, message: str) -> None:
        """Send a message to the live chat with robust truncation"""
        try:
            # Truncate message if too long
            message = (message[:self.MAX_MESSAGE_LENGTH] + 
                       ("..." if len(message) > self.MAX_MESSAGE_LENGTH else "")).strip()
            
            self.youtube.liveChatMessages().insert(
                part="snippet",
                body={
                    "snippet": {
                        "liveChatId": livechat_id,
                        "type": "textMessageEvent",
                        "textMessageDetails": {
                            "messageText": message
                        }
                    }
                }
            ).execute()
        except Exception as e:
            self.logger.error(f"Error sending message: {e}")

    def get_live_chat_id(self) -> Optional[str]:
        """Get the live chat ID of the current stream"""
        try:
            response = self.youtube.liveBroadcasts().list(
                part="snippet",
                broadcastStatus="active"
            ).execute()
            
            return response['items'][0]['snippet']['liveChatId'] if response.get('items') else None
                
        except Exception as e:
            self.logger.error(f"Error getting live chat ID: {e}")
            return None

    def clean_cooldowns(self) -> None:
        """Remove old cooldown entries"""
        now = time.time()
        self.command_cooldown = {
            k: v for k, v in self.command_cooldown.items() 
            if now - v < self.COOLDOWN_DURATION
        }

    def ollama_bot(self, command: str, livechat_id: str) -> None:
        """Process AI-powered chat responses"""
        if not command.lower().startswith('!ai'):
            return

        try:
            # Extract user message
            _, user_message = command.split(' ', 1)
            
            # Prepare prompt templates
            system_message = SystemMessagePromptTemplate.from_template(
                "Respond in Hinglish if asked and reply with fun, friendly, and witty humor. Keep all responses under 10 characters. Add roasts for extra entertainment."
            )
            human_message = HumanMessagePromptTemplate.from_template(
                "{username} says: {message}"
            )
            chat_prompt = ChatPromptTemplate.from_messages([system_message, human_message])

            # Configure Ollama model
            model = OllamaLLM(
                model="llama3.1", 
                temperature=0.83, 
                max_tokens=40
            )

            # Generate and send response
            result = model.invoke(
                chat_prompt.format(username="User", message=user_message)
            )
            self.send_message(livechat_id, result)
            
        except ValueError:
            self.send_message(livechat_id, "Please provide a message after !ai")
        except Exception as e:
            self.logger.error(f"Ollama bot error: {e}")

    def handle_command(self, command: str, livechat_id: str) -> None:
        """Handle predefined bot commands"""
        command_map = {
            '!hello': "Hello! Welcome to the stream! 👋",
            '!commands': """Available commands:
            !hello - Get a welcome message
            !commands - Show this list
            !discord - Get Discord link
            !socials - Get social media links
            !ai <text> - Talk to AI""",
            '!discord': "Join our Discord: [Your Discord]",
            '!socials': """Follow me on:
            Instagram: [Your Instagram]"""
        }
        
        response = command_map.get(command)
        if response:
            self.send_message(livechat_id, response)

    def handle_chat(self, livechat_id: str) -> None:
        """Handle incoming chat messages with improved error handling"""
        bot_start_time = datetime.now(timezone.utc)
        next_page_token = None

        try:
            while True:
                try:
                    # Clean up old cooldowns periodically
                    self.clean_cooldowns()

                    # Retrieve chat messages
                    request = self.youtube.liveChatMessages().list(
                        liveChatId=livechat_id,
                        part="snippet",
                        maxResults=25,
                        pageToken=next_page_token
                    )
                    
                    response = request.execute()
                    
                    for message in response.get('items', []):
                        mt = datetime.strptime(
                            message['snippet']['publishedAt'], 
                            '%Y-%m-%dT%H:%M:%S.%f%z'
                        )
                        
                        # Robust time comparison
                        if mt > bot_start_time:
                            text = message['snippet']['textMessageDetails']['messageText']
                            user_id = message['snippet']['authorChannelId']

                            if text.lower().startswith('!ai'):
                                if time.time() - self.command_cooldown.get(user_id, 0) > self.COOLDOWN_DURATION:
                                    self.command_cooldown[user_id] = time.time()
                                    self.ollama_bot(text, livechat_id)
                            elif text.startswith('!'):
                                self.handle_command(text.lower(), livechat_id)

                    # Update pagination token
                    next_page_token = response.get('nextPageToken')
                    
                    # Manage polling interval
                    interval = max(response.get('pollingIntervalMillis', 10000) / 1000, 10)
                    time.sleep(interval)
                
                except Exception as e:
                    self.logger.error(f"Error in polling loop: {e}")
                    time.sleep(10)  # Prevent rapid retries
        
        except Exception as e:
            self.logger.error(f"Critical error handling chat: {e}")

def main():
    bot = YouTubeBot()
    livechat_id = bot.get_live_chat_id()
    
    if livechat_id:
        try:
            print("Connected to live chat!")
            bot.handle_chat(livechat_id)
        except Exception as e:
            bot.logger.critical(f"Fatal error in main chat handling: {e}")
    else:
        print("No active live stream found.")

if __name__ == "__main__":
    main()
