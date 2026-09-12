# First-play playback fix

The bot now uses the API's `/direct` endpoint for audio:

1. It sends the API key in the `X-API-Key` header.
2. It parses the JSON response and reads its signed `url`.
3. It downloads that signed URL explicitly.
4. It writes to a `.part` file and renames it only after a non-empty response.

This avoids treating `/download?type=audio`'s `302` response as an audio body.
Video downloads keep the existing `/download?type=video` path.

On the API deployment, use:

```bash
heroku config:set YOUTUBE_USE_COOKIES=false --app music-apii-76201ebccbfa
```

Also rotate any API key that was exposed in logs or chat, then set the same
new value as `API_KEY` on the API and `ARTISTBOTS_KEY` on the bot.