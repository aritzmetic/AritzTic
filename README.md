# Aritztic

Run locally: `pip install -r requirements.txt`, save your Firebase key as `serviceAccountKey.json` next to `app.py`, then `python app.py`.

Vercel: set one env var, `FIREBASE_SERVICE_ACCOUNT` = the entire contents of the service-account JSON file (raw JSON or base64). Redeploy. Open `/api/health`; it should say `"firestore": "ok (...)"`.

Never commit `serviceAccountKey.json`. Google disables keys it finds in public repos, which causes `invalid_grant: Invalid JWT Signature`.
