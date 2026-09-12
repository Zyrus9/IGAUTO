# IGAUTO — Daily Quote Instagram Bot

Every day this bot:
1. Fetches a quote from [ZenQuotes](https://zenquotes.io) (free, no key needed)
2. Detects a rough "theme" (love, success, motivation, time, growth, wisdom, life)
3. Renders the quote as a 1080x1080 image with a gradient background
4. Picks a matching song recommendation and builds hashtags
5. Uploads the image to Imgur (to get a public URL, which Instagram's API requires)
6. Publishes it to your Instagram account via the Graph API
7. Saves a record (image + quote + song + hashtags) under `posts/YYYY-MM-DD/`

It runs automatically every day via GitHub Actions — your computer doesn't need to be on.

## 1. Push this to a GitHub repo

Create a new **private** repo (recommended, since it'll contain your posting history)
and push these files to it.

## 2. Get an Imgur Client ID

1. Go to https://api.imgur.com/oauth2/addclient
2. Fill in an application name, choose **"Anonymous usage without user authorization"**
3. You'll get a **Client ID** — that's all you need, no OAuth login required.

## 3. Add your secrets to GitHub

In your repo: **Settings → Secrets and variables → Actions → New repository secret.**
Add these three:

| Secret name | Value |
|---|---|
| `IG_ACCESS_TOKEN` | Your long-lived Instagram access token (from the Meta App Dashboard) |
| `IG_USER_ID` | Your Instagram business account ID — e.g. `17841462869952779` |
| `IMGUR_CLIENT_ID` | The Client ID from step 2 |

## 4. Test it before trusting it

**Locally, without posting anything:**
```bash
pip install -r requirements.txt
DRY_RUN=true python bot.py
```
This generates the image and prints the caption, but skips Imgur and Instagram entirely.
Check `/tmp/quote_card.jpg` to see how it looks.

**On GitHub, without posting anything:**
Go to the **Actions** tab → **Daily Quote Post** → **Run workflow** → check the
"Dry run" box → **Run workflow**. Check the logs for the caption preview.

**A real live test post:**
Run the workflow again with "Dry run" unchecked, or just wait for the schedule.

## 5. Adjust the posting time

Edit the `cron` line in `.github/workflows/daily-quote-post.yml`. It's currently
`0 13 * * *` (13:00 UTC = 6:30 PM IST). Cron times are always in UTC.

## Heads up: token expiry

Long-lived Instagram tokens last about **60 days**. Set yourself a reminder to
regenerate one every ~50 days from the same "API setup with Instagram login" page
you used originally, and update the `IG_ACCESS_TOKEN` secret. (This can be
automated later with the token-refresh endpoint if you want — just ask.)

## Customizing

- **Themes / hashtags / songs**: edit the `THEMES` dict near the top of `bot.py`.
- **Colors**: edit `BACKGROUND_PALETTES`.
- **Posting time**: edit the cron schedule (step 5 above).
- **Caption wording**: edit `build_caption()`.
