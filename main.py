from googleapiclient.discovery import build
import pickle
import time
from langchain_ollama import OllamaLLM
from langchain_core.prompts import ChatPromptTemplate, HumanMessagePromptTemplate, SystemMessagePromptTemplate

class YouTubeBot:
    def __init__(self):
        # Load the credentials from the pickle file
        with open('youtube_token_sense.pickle', 'rb') as token:
            credentials = pickle.load(token)
            
        # Create YouTube API service
        self.youtube = build('youtube', 'v3', credentials=credentials,cache_discovery=True)
        self.command_cooldown = {}
    def send_message(self, livechat_id, message):
        """Send a message to the live chat"""
        try:
            # Ensure message isn't too long (YouTube has a character limit)
            if len(message) > 200:  # YouTube's limit is around 200 characters
                message = message[:197] + "..."
            
            message = message.strip()
            
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
            print(f"Error sending message: {e}")

    def get_live_chat_id(self):
        """Get the live chat ID of the current stream"""
        try:
            request = self.youtube.liveBroadcasts().list(
                part="snippet",
                broadcastStatus="active"
            )
            response = request.execute()
            
            if 'items' in response and len(response['items']) > 0:
                return response['items'][0]['snippet']['liveChatId']
            else:
                return None
                
        except Exception as e:
            print(f"Error getting live chat ID: {e}")
            return None

    def handle_chat(self, livechat_id):
        """Handle incoming chat messages"""
        next_page_token = None
        try:
            while True:
                try:
                    request = self.youtube.liveChatMessages().list(
                        liveChatId=livechat_id,
                        part="snippet",
                        maxResults=25,
                        pageToken=next_page_token
                    ) if next_page_token else self.youtube.liveChatMessages().list(
                        liveChatId=livechat_id,
                        part="snippet",
                        maxResults=25
                    )
                    
                    response = request.execute()
                    
                    for message in response.get('items', []):
                        text = message['snippet']['textMessageDetails']['messageText']
                        
                        if text.lower().startswith('!ai'):
                            user_id = message['snippet']['authorChannelId']
                            if time.time() - self.command_cooldown.get(user_id, 0) > 30:
                                self.command_cooldown[user_id] = time.time()
                                self.ollama_bot(text, livechat_id)
                        elif text.startswith('!'):
                            self.handle_command(text.lower(), livechat_id)

                    # Update the next_page_token from the response
                    next_page_token = response.get('nextPageToken')
                    
                    interval = response.get('pollingIntervalMillis', 10000) / 1000
                    time.sleep(max(interval, 10))
                
                except Exception as e:
                    print(f"Error in polling loop: {e}")
                    time.sleep(10)  # Prevent rapid retries
        except Exception as e:
            print(f"Error handling chat: {e}")

    def ollama_bot(self,command,livechat_id):
        if command.lower().startswith('!ai'):  # Changed 'text' to 'command'
            try:
                _, user_message = command.split(' ', 1)
                system_message = SystemMessagePromptTemplate.from_template(
                "Keep all responses under 200 characters."
                "You are a fun, friendly, and witty Indian Hinglish chatbot designed to engage with viewers in a YouTube livestream chat."
                "Add roasts for added humour"
                )

                human_message = HumanMessagePromptTemplate.from_template(
                "{username} says: {message}")
                chat_prompt = ChatPromptTemplate.from_messages([system_message, human_message])

                model =  OllamaLLM(model="llama3.1",temperature=0.7)

                result =  model.invoke(chat_prompt.format(username="User", message=user_message))
                print(command)
                print(result)
                self.send_message(livechat_id,result)
                
            except ValueError:
                # Handle case where no message follows !ai
                self.send_message(livechat_id, "Please provide a message after !ai")

    def handle_command(self, command, livechat_id):
        """Handle bot commands"""
        
        if command == '!hello':
            self.send_message(livechat_id, "Hello! Welcome to the stream! 👋")
            
        elif command == '!commands':
            commands_list = """Available commands:
            !hello - Get a welcome message
            !commands - Show this list
            !discord - Get Discord link
            !socials - Get social media links
            !ai <text> - Talk to AI"""
            self.send_message(livechat_id, commands_list)
            
        elif command == '!discord':
            self.send_message(livechat_id, "Join our Discord: [Your Discord]")
            
        elif command == '!socials':
            social_links = """Follow me on:
            Instagram: [Your Instagram]"""
            self.send_message(livechat_id, social_links)

def main():
    bot = YouTubeBot()
    # Get live chat ID
    #DAXXYFTW
    livechat_id = bot.get_live_chat_id()
    
    if livechat_id:
        print("Connected to live chat!")
        bot.handle_chat(livechat_id)
    else:
        print("No active live stream found.")

if __name__ == "__main__":
    main()
