# Deployment Guide — Get a Free Public URL in 10 Minutes

This guide walks you through deploying the Nonprofit Compliance Auditor on **Streamlit Cloud** so anyone can open it with one click — no installation, no login required.

---

## Option A — Deploy on Streamlit Cloud (Recommended)

Streamlit Cloud is free for public repositories and gives you a permanent public URL instantly.

### Step 1 — Confirm your `requirements.txt` exists

Your project already has a `requirements.txt` at the root. Streamlit Cloud reads it automatically to install dependencies. No changes needed.

### Step 2 — Push your project to a public GitHub repository

If your repository is already public on GitHub, skip to Step 3.

1. Go to [github.com](https://github.com) and sign in (or create a free account).
2. Click **New repository**.
3. Name it (e.g., `nonprofit-compliance-auditor`), set it to **Public**, and click **Create repository**.
4. Push your local code:

```bash
git remote add origin https://github.com/YOUR_GITHUB_USERNAME/nonprofit-compliance-auditor.git
git branch -M main
git push -u origin main
```

> If you already have a remote set up, just run `git push origin main`.

### Step 3 — Connect to Streamlit Cloud

1. Go to [share.streamlit.io](https://share.streamlit.io) and sign in with your GitHub account.
2. Click **New app**.
3. Select your repository (`nonprofit-compliance-auditor`) from the dropdown.
4. Set the **Branch** to `main` (or `master`).
5. Set the **Main file path** to `app.py`.
6. Click **Deploy**.

Streamlit Cloud will install your dependencies and start the app. This takes 2–5 minutes the first time.

### Step 4 — Get your public URL

Once the deploy completes, Streamlit Cloud shows your app at a URL like:

```
https://YOUR_GITHUB_USERNAME-nonprofit-compliance-auditor-app-XXXX.streamlit.app
```

Copy this URL.

### Step 5 — Update the landing page

Open `LANDING_PAGE.md` and replace `YOUR_PUBLIC_APP_URL` with your real URL:

```markdown
[![Open App](https://img.shields.io/badge/Open%20App-Nonprofit%20Compliance%20Auditor-blue?style=for-the-badge)](https://your-real-url.streamlit.app)
```

Then commit and push:

```bash
git add LANDING_PAGE.md
git commit -m "Add public app URL to landing page"
git push origin main
```

---

## Option B — Deploy on Hugging Face Spaces

Hugging Face Spaces also supports Streamlit apps for free.

### Step 1 — Create a Hugging Face account

Go to [huggingface.co](https://huggingface.co) and sign up for a free account.

### Step 2 — Create a new Space

1. Click your profile → **New Space**.
2. Name it (e.g., `nonprofit-compliance-auditor`).
3. Choose **Streamlit** as the SDK.
4. Set visibility to **Public**.
5. Click **Create Space**.

### Step 3 — Push your code to the Space

Hugging Face Spaces use a Git repository. Clone the empty Space, copy your project files into it, and push:

```bash
git clone https://huggingface.co/spaces/YOUR_HF_USERNAME/nonprofit-compliance-auditor
cd nonprofit-compliance-auditor
# Copy all your project files here
git add .
git commit -m "Initial deployment"
git push
```

### Step 4 — Get your public URL

Your app will be live at:

```
https://huggingface.co/spaces/YOUR_HF_USERNAME/nonprofit-compliance-auditor
```

### Step 5 — Update the landing page

Same as Option A, Step 5 — replace `YOUR_PUBLIC_APP_URL` in `LANDING_PAGE.md` with your Hugging Face Spaces URL.

---

## Important Note — Ollama on Cloud

The Nonprofit Compliance Auditor uses **Ollama for local LLM inference**. Cloud deployment platforms (Streamlit Cloud, Hugging Face Spaces) do not provide a local Ollama server.

To run the full AI pipeline on a cloud deployment, you have two options:

### Option 1 — Use the Ollama API environment variable
If you have an Ollama server running on a remote machine or VPS, set the `OLLAMA_HOST` environment variable in your Streamlit Cloud app settings:

1. In your Streamlit Cloud app dashboard, go to **Settings → Secrets**.
2. Add:
```toml
OLLAMA_HOST = "http://YOUR_OLLAMA_SERVER_IP:11434"
```

### Option 2 — Replace Ollama with a cloud LLM (advanced)
Swap `ChatOllama` in the agents for `ChatOpenAI` or another LangChain-compatible provider, and add the API key to Streamlit Cloud secrets. This requires code changes but gives full cloud compatibility.

---

## Summary Checklist

- [ ] `requirements.txt` exists at project root (already done)
- [ ] Project is pushed to a public GitHub repository
- [ ] Streamlit Cloud account created at [share.streamlit.io](https://share.streamlit.io)
- [ ] App deployed — main file: `app.py`
- [ ] Public URL copied
- [ ] `LANDING_PAGE.md` updated with real URL
- [ ] Changes pushed to GitHub
