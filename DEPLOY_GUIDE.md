# ConsolidaTrack — Deploy to Render (Free)

## Step 1: Create GitHub Account (if you don't have one)
1. Go to https://github.com
2. Sign up → verify email

## Step 2: Install Git
1. Download: https://git-scm.com/download/win
2. Install with default options
3. Open terminal and configure:
```
git config --global user.name "Your Name"
git config --global user.email "your@email.com"
```

## Step 3: Push Your Project to GitHub
In your project folder, run these commands ONE BY ONE:
```
cd "J:\My Drive\my proyect\controla containers\consolidatrack\consolidation-system"
git init
git add .
git commit -m "Initial commit"
```

Then go to GitHub → New Repository → name it `consolidatrack` → Create.
GitHub will show you commands. Run:
```
git remote add origin https://github.com/YOUR_USERNAME/consolidatrack.git
git branch -M main
git push -u origin main
```

## Step 4: Create Render Account
1. Go to https://render.com
2. Sign up with GitHub (easiest)

## Step 5: Deploy on Render
### Option A: Using render.yaml (automatic)
1. In Render dashboard → "New" → "Blueprint"
2. Connect your GitHub repo
3. Render reads `render.yaml` and creates everything automatically
4. Wait 5-10 minutes for build

### Option B: Manual setup
1. **Create PostgreSQL database:**
   - New → PostgreSQL → Free plan → Create
   - Copy the "Internal Database URL"

2. **Create Web Service:**
   - New → Web Service → Connect your repo
   - Runtime: Python
   - Build Command: `./build.sh`
   - Start Command: `gunicorn wsgi:app`
   - Plan: Free
   - Add Environment Variables:
     - `DATABASE_URL` = (paste the database URL)
     - `SECRET_KEY` = (any random long string)
     - `UPLOAD_FOLDER` = `/opt/render/project/src/uploads/photos`

3. Click "Create Web Service" → wait for deploy

## Step 6: Access Your App
Your URL will be: `https://consolidatrack.onrender.com`
(or whatever name Render assigns)

## Default Login
- Email: `admin@consolidatrack.com`
- Password: `admin123`
- **CHANGE THIS IMMEDIATELY** after first login!

## Notes
- Free plan sleeps after 15 min of inactivity (takes ~30s to wake up)
- Free PostgreSQL expires after 90 days (you can recreate it)
- Photos/PDFs uploaded will persist until the service redeploys
- For permanent file storage, consider upgrading to paid plan or using S3

## Updating the App
When you make changes locally:
```
git add .
git commit -m "Description of changes"
git push
```
Render auto-deploys on every push!
