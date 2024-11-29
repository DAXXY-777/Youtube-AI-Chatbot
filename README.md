# Youtube-AI-Chatbot

## Overview
This Python script is a chatbot designed for YouTube live streams. It uses the YouTube Data API to interact with live chat messages and integrates AI capabilities via the `OllamaLLM` from LangChain. The AI provides witty, multilingual responses to user commands like `!ai` and supports other commands such as `!hello`, `!discord`, and `!socials`.

---

## Features
1. **YouTube Live Chat Interaction**:  
   - Connects to an active YouTube live stream.  
   - Monitors chat messages and responds to supported commands.  

2. **AI-Powered Responses**:  
   - Integrates with `OllamaLLM` to generate dynamic, context-aware replies.  
   - Supports English, Hindi, and mixed-language responses for humor.  

3. **Command Cooldown**:  
   - Prevents spamming by applying cooldowns to commands like `!ai`.  

4. **Predefined Commands**:  
   - `!hello`: Sends a friendly welcome message.  
   - `!commands`: Lists available commands.  
   - `!discord`: Shares a Discord invite link.  
   - `!socials`: Provides social media links.  

---

## Prerequisites
### 1. Install Required Python Libraries
Install the dependencies using `pip`:
```bash
pip install google-api-python-client pickle5 langchain
```

### 2. Configure YouTube API
1. Enable the **YouTube Data API v3** in Google Cloud Console.
2. Save your credentials to a file named `youtube_token.pickle`.

### 3. Install and Run Ollama
1. **Install Ollama**:
   - Download and install Ollama from its [official website](https://ollama.ai/).
   - Follow the setup instructions for your operating system.

2. **Start the Ollama Service**:
   - Run the Ollama service locally:
     ```bash
     ollama serve
     ```
   - Ensure the service is running before launching the bot.

3. **Install AI Model**:
   - Ensure the model is available on your Ollama instance.

### 4. Environment Requirements
- Python 3.8+
- Local network or environment capable of running the bot and Ollama.

---

## Usage
### Run the Script
```bash
python youtube_chat_bot.py
```

### Expected Behavior
- The bot will connect to your active live stream's chat.
- Responds to supported commands as users interact in the chat.

---

## Commands
| Command       | Description                                                                                     |
|---------------|-------------------------------------------------------------------------------------------------|
| `!ai <text>`  | Generates an AI-driven response based on the provided text.                                     |
| `!hello`      | Sends a welcome message to the live chat.                                                       |
| `!commands`   | Displays a list of available commands.                                                          |
| `!discord`    | Shares a Discord invite link.                                                                   |
| `!socials`    | Provides links to social media accounts.                                                        |

---

## Customization
1. **Adding New Commands**:
   - Add new commands in the `handle_command()` method.

2. **Modifying AI Behavior**:
   - Adjust the `system_message` prompt in `ollama_bot()` to change the AI's tone or capabilities.

3. **Updating Links**:
   - Replace placeholders in the `!discord` and `!socials` commands with your actual URLs.

---

## Troubleshooting
### Common Issues
1. **Ollama Not Running**:
   - Ensure the `ollama serve` command is running locally.

2. **No Active Live Stream Found**:
   - Confirm that a live stream is running and the authenticated account has access.

3. **YouTube API Quota Exceeded**:
   - Check your API usage in the Google Cloud Console and increase quota if necessary.

4. **AI Model Errors**:
   - Verify the model you use is installed and accessible by the Ollama server.
   - Check using 'ollama list' in cmd 

---

## Acknowledgments
- **Google API Client Library**: For YouTube integration.
- **Ollama and LangChain**: For AI chatbot functionality.

Enjoy engaging with your audience in real-time! 🚀
Google API Client Library: For YouTube integration.
Ollama and LangChain: For AI chatbot functionality.
Enjoy engaging with your audience in real-time! 🚀
