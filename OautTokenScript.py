from google_auth_oauthlib.flow import InstalledAppFlow
import pickle

# YouTube API scopes
SCOPES = [
    'https://www.googleapis.com/auth/youtube.readonly',
    'https://www.googleapis.com/auth/youtube'
]

def generate_oauth_token(client_secrets_file='csx.json'):
    """
    Generate and save OAuth token
    
    Args:
        client_secrets_file (str): Path to downloaded client secrets JSON
    """
    try:
        # Create flow instance
        flow = InstalledAppFlow.from_client_secrets_file(
            client_secrets_file, 
            SCOPES
        )
        
        # Run local server for authorization
        credentials = flow.run_local_server(port=0)
        
        # Save credentials for future use
        with open('youtube_token.pickle', 'wb') as token_file:
            pickle.dump(credentials, token_file)
        
        print("OAuth token generated and saved successfully!")
        print(f"Access Token: {credentials.token}")
    
    except Exception as e:
        print(f"Error generating token: {e}")

# Run the token generation
generate_oauth_token()
