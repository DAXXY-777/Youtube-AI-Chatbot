#ifndef MyAppVersion
  #define MyAppVersion "0.1.0"
#endif

#ifndef SourceDir
  #define SourceDir "..\dist\YT Livestream Chatbot"
#endif

[Setup]
AppId={{A7D48216-6C01-4A32-9B8A-218440A159B1}
AppName=YT Livestream Chatbot
AppVersion={#MyAppVersion}
AppPublisher=YT Livestream Chatbot contributors
DefaultDirName={userdocs}\YT Livestream Chatbot
DefaultGroupName=YT Livestream Chatbot
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\release
OutputBaseFilename=YT-Livestream-Chatbot-Setup-{#MyAppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\YT Livestream Chatbot"; Filename: "{app}\YT Livestream Chatbot.exe"
Name: "{autodesktop}\YT Livestream Chatbot"; Filename: "{app}\YT Livestream Chatbot.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"

[Run]
Filename: "{app}\YT Livestream Chatbot.exe"; Description: "Launch YT Livestream Chatbot"; Flags: nowait postinstall skipifsilent
