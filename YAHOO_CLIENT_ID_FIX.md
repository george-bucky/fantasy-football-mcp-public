# Fix Yahoo "Invalid Client ID" Error

## The Problem
Yahoo is saying your client ID is invalid or unauthorized. This means either:
1. The client ID is wrong
2. The app was deleted
3. The app isn't active yet
4. You're using the wrong format

## Check Your Client ID Format

Your current client ID:
```
[YOUR_CLIENT_ID_HERE]
```

This looks like it might be **base64 encoded** or includes extra parameters (`&s=consumerscret&sv=0&x=cc`).

## Solution 1: Get Your Real Client ID

1. **Go to** https://developer.yahoo.com/apps/
2. **Sign in** with your Yahoo account
3. **Look for your app** - do you see it listed?

If you see your app:
- Click on it
- Look for **"App ID"** or **"Client ID"** (NOT Consumer Key)
- It should look like: `dj0yJmk9XXXXXXXXX` (shorter, no extra parameters)

## Solution 2: Your App May Have Been Deleted

If you don't see any apps:
1. Your app was deleted or never created properly
2. You need to create a new one

## Solution 3: Create a New Yahoo App (RECOMMENDED)

Since your current credentials aren't working, create a fresh app:

### Step 1: Create New App
1. Go to https://developer.yahoo.com/apps/create/
2. Fill in:
   ```
   App Name: Fantasy Football MCP 2024
   Description: Personal fantasy football assistant
   Home Page URL: https://localhost:8000
   Redirect URI(s): https://localhost:8000
   ```
3. Under **API Permissions**, check:
   - **Fantasy Sports** → **Read**
4. Click **Create App**

### Step 2: Get Your Credentials
After creation, you'll see:
- **App ID** (also called Client ID) - looks like `dj0yJmk9XXXXXXXXX`
- **Client Secret** - a long random string

**IMPORTANT**: Copy these EXACTLY as shown, no modifications!

### Step 3: Test New Credentials
Update your `.env` file:
```env
YAHOO_CLIENT_ID=your_new_app_id_here
YAHOO_CLIENT_SECRET=your_new_client_secret_here
```

Then test with:
```
https://api.login.yahoo.com/oauth2/request_auth?client_id=YOUR_NEW_CLIENT_ID&redirect_uri=https://localhost:8000&response_type=code
```

## Common Mistakes

### ❌ Wrong Client ID Format
```
# WRONG - includes extra parameters
[FULL_KEY_WITH_PARAMETERS]

# RIGHT - just the client ID
[CLIENT_ID_ONLY]
```

### ❌ Using Consumer Key Instead of Client ID
Yahoo shows both - make sure you're using the right one!

### ❌ App Not Active
New apps can take 5-10 minutes to activate.

## Quick Debug Test

Run this Python script to check your credentials:
```python
import base64

# Your current ID
client_id = "[YOUR_CLIENT_ID_HERE]"

# Check if it's base64 encoded
try:
    decoded = base64.b64decode(client_id)
    print(f"Decoded: {decoded}")
    # If this works, you might be using an encoded version
except:
    print("Not base64 encoded")

# Check for URL parameters
if "&" in client_id:
    print("\n⚠️  Your client ID contains URL parameters!")
    print("Real client ID might be:", client_id.split("&")[0])
```

## The Bottom Line

Your client ID appears to be malformed or includes extra data. You need to either:
1. Get the correct client ID from your Yahoo app page
2. Create a new app with fresh credentials

Most likely, you need to **create a new app** since the current credentials aren't being recognized by Yahoo.