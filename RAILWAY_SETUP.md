# Railway Deployment Setup

## Fixed Issues ✅

1. **Missing psycopg2-binary** - Added to requirements.txt
2. **Missing Procfile** - Created with correct uvicorn command
3. **PORT environment variable** - Config now reads from Railway's PORT env var
4. **DATABASE_URL** - Config now uses Railway's DATABASE_URL automatically

## Railway Environment Variables

Set these in Railway dashboard → Variables:

### Required
- `DATABASE_URL` - Automatically provided by Railway PostgreSQL service
- `PORT` - Automatically set by Railway

### Optional (for full functionality)
- `GREENHOUSE_API_KEY` - Your Greenhouse Harvest API key
- `GREENHOUSE_WEBHOOK_SECRET` - Webhook secret for signature verification
- `MS_TENANT_ID` - Microsoft Graph tenant ID
- `MS_CLIENT_ID` - Microsoft Graph client ID  
- `MS_CLIENT_SECRET` - Microsoft Graph client secret
- `ENVIRONMENT=production`
- `DEBUG=false`
- `ADMIN_USERNAME=admin`
- `ADMIN_PASSWORD=<secure-password>`

## Deployment Status

✅ Code pushed to GitHub
✅ Railway will auto-deploy
✅ All dependencies included
✅ Procfile created
✅ Environment variable support added

The deployment should now work! Railway will:
1. Install all dependencies (including psycopg2-binary)
2. Use the Procfile to start the server
3. Connect to PostgreSQL automatically
4. Use the PORT environment variable

Check Railway dashboard for the new deployment status.
