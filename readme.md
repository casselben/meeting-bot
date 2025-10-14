uvicorn app.server:app --host 0.0.0.0 --port 8000
# Create bot (uses recallai_streaming; region is parametric)
curl -X POST "https://$RECALL_REGION.recall.ai/api/v1/bot" \
  -H "authorization: Token $RECALL_API_KEY" -H "content-type: application/json" \
  -d '{
    "meeting_url": "MEETING_URL",
    "external_id": "ext-123",
    "webhook_url": "https://your-app/webhook",
    "recording_config": {
      "transcript": { "provider": { "recallai_streaming": { "language_code": "en" } } },
      "video_mixed_mp4": {},
      "audio_mixed_mp3": {}
    }
  }'


# How to build a meeting bot

This example shows how to build a meeting bot using **Recall.ai** and **FastAPI**.  
The bot can join Zoom, Google Meet, or Microsoft Teams calls, record them, and retrieve transcripts or media.

## Prerequisites

Before you start, install:

- [Python 3.9+](https://www.python.org/downloads/)
- [pip](https://pip.pypa.io/en/stable/installation/)
- [ngrok](https://ngrok.com/)
- A free [Recall.ai account](https://us-west-2.recall.ai/auth/signup)

## 1. Clone the repository

```bash
git clone https://github.com/your-username/recall-meeting-bot-demo.git
cd recall-meeting-bot-demo
```

## 2. Create a Virtual Env

```bash
python3 -m venv venv
source venv/bin/activate      # macOS/Linux
# OR
venv\Scripts\activate         # Windows
```

## 3. Install dependencies
``` bash
pip install -r requirements.txt
```
If the file is missing run:
``` bash
pip install fastapi uvicorn httpx python-dotenv
```

## 4. Set env variables
Creat a `.env` file at the root:
``` bash
RECALL_API_KEY=your_recall_api_key
RECALL_REGION=us-east-1
NGROK_BASE=https://your-subdomain.ngrok-free.app
WS_TOKEN=random_secret_here
```

> DO NOT commit `.env` files to GitHub (or anywhere else). `.env` files typically hold sensitive info like API keys, tokens, etc.

## 5. Start ngrok
Expose the local server so that Recall.ai can reach it.
``` bash
ngrok http 8000
```
Copy the HTTPS forwarding URL and set it as `NGROK_BASE` in your `.env`.

## 6. Run the FastAPI server
``` bash
uvicorn app.main_pro:app --host 0.0.0.0 --port 8000
```
Check that it's running by visiting: 
http://localhost:8000/

## 7. Create your bot
In a new terminal window run:
``` bash
curl -X POST "https://$RECALL_REGION.recall.ai/api/v1/bot" \
  -H "authorization: Token $RECALL_API_KEY" \
  -H "content-type: application/json" \
  -d '{
    "meeting_url": "PASTE_YOUR_MEETING_LINK",
    "webhook_url": "https://your-subdomain.ngrok-free.app/wh",
    "recording_config": {
      "transcript": { "provider": { "recallai_streaming": { "language_code": "en" } } },
      "audio_mixed_mp3": {},
      "video_mixed_mp4": {}
    }
  }'
```
Adjust your curl to match the artifacts/data you want. This example does not include [real-time transcription]() or [output media]() because I did not subscribe to transcription events. See the [docs]() or our blog on [how to build a meeting bot]() to learn more.

You’ll get a JSON response with a `bot_id`.

> If your meeting requires host approval/is private and requires a password, you must make sure to let your bot into the meeting/provide the appropriate url to let the bot join.

## 8. Retrieve meeting data
After the meeting ends:
``` bash
curl "http://localhost:8000/retrieve/YOUR_BOT_ID"
```
This returns JSON with URLs to download your audio, video, and transcript files.