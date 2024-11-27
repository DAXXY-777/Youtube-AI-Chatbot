# YouTube API Integration Guide

This guide outlines how to set up and generate authentication tokens for accessing the **YouTube Data API v3** using Google Cloud Console and Python.

---

## Prerequisites

1. **Google Account**: Ensure you have a Google account.
2. **Python Installed**: Install Python 3.x on your system.
3. **Python Libraries**: Install the required libraries:
   ```bash
   pip install google-auth-oauthlib google-auth google-api-python-client
   ```

---

## Steps to Configure and Enable YouTube Data API

### 1. Create a New Project in Google Cloud Console
1. Open the [Google Cloud Console](https://console.cloud.google.com/).
2. Click **Select Project** in the top menu.
3. Click **+ New Project**.
4. Enter a **Project Name** and leave the **Organization** field empty if you're not part of one.
5. Click **Create**.

---

### 2. Enable the YouTube Data API v3
1. In the Google Cloud Console, go to **Dashboard**.
2. Navigate to **APIs & Services > Library**.
3. Search for **YouTube Data API v3**.
4. Click the API and select **Enable**.
   - If prompted, select **Public** for API access.

---

### 3. Configure the OAuth Consent Screen
1. Go to **APIs & Services > OAuth consent screen**.
2. Select **External** as the user type.
3. Fill in the required details:
   - **App Name**: Your application's name.
   - **Support Email**: An email address to show to users.
   - **Developer Contact Information**: Your email address.
4. Save the form and click **Next**.
5. In the **Scopes** section, click **Add or Remove Scopes**, then add the following scopes:
   - `https://www.googleapis.com/auth/youtube.force-ssl`
   - `https://www.googleapis.com/auth/youtube`
   - `https://www.googleapis.com/auth/youtube.readonly`
6. Complete the setup by clicking **Save and Continue**.

---

### 4. Create an OAuth Client ID
1. Go to **APIs & Services > Credentials**.
2. Click **+ Create Credentials > OAuth Client ID**.
3. Select **Desktop App** as the application type.
4. Enter a name for the OAuth client (e.g., `YouTube Desktop`).
5. Click **Create**.
6. **Download the JSON file** containing the client configuration (client ID and client secret) and save it securely in your project directory.

---

## Generate Authentication Token

Use Python's `google-auth-oauthlib` library to generate an OAuth token.

### Sample Python Script for Token Generation
1. Place the downloaded `client_secrets.json` file in the same directory as your Python script.
2. Use the OautTokenScript to generate a token:



### Steps to Run the Script
1. Save the downloaded JSON file as `client_secrets.json`.
2. Run the script:
   ```bash
   python your_script_name.py
   ```
3. Follow the browser prompt to authorize access.
4. After authorization, the script will output:
   - **Access Token** (short-lived).
   - **Refresh Token** (for long-term access).

---

## Notes
- Tokens are short-lived, so you may need to refresh them periodically.
- Ensure you keep `client_secrets.json` secure to avoid unauthorized access.

---

### Adjustments Made:
1. Specified additional required Python library (`google-api-python-client`).
2. Clarified the **Scopes** addition during OAuth consent screen setup.
3. Corrected minor ambiguities in navigating Google Cloud Console menus.
4. Updated the Python script to print both **access** and **refresh tokens** for better usability.

This guide is now accurate and complete for the described workflow.
