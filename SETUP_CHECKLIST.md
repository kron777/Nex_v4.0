# NEX v4.0 — Monetization Setup Checklist

Follow these steps in order. Takes about 15 minutes total.

---

## STEP 1 — Make GitHub Repo Private

1. Go to: https://github.com/kron777/Nex_v4.0
2. Click **Settings** (top right of repo)
3. Scroll to the bottom → **Danger Zone**
4. Click **Change visibility** → **Make private**
5. Confirm

⚠️ Do this FIRST — otherwise anyone can clone it for free right now.

---

## STEP 2 — Add README and LICENSE to Repo

Upload the two files provided (README.md and LICENSE) to your repo root.

Either:
- Drag and drop them into github.com/kron777/Nex_v4.0, or
- From your terminal:
  ```bash
  cd ~/Desktop/nex
  cp /path/to/README.md .
  cp /path/to/LICENSE .
  git add README.md LICENSE
  git commit -m "add: commercial license and README"
  git push
  ```

---

## STEP 3 — Set Up Gumroad (for card/PayPal payments)

1. Go to **https://gumroad.com** → Sign up (free)
2. Click **"New Product"** → **"Digital product"**
3. Fill in:
   - **Name:** `NEX v4.0 — Autonomous AI Agent`
   - **Price:** `$49`
   - **Description:** copy from README.md (the "What NEX Does" section)
   - **File to deliver:** Upload a .txt file that says:
     > "Thank you for purchasing NEX v4.0. Reply to your receipt email with your GitHub username and you'll receive repo access within 24 hours."
4. Publish it
5. Copy your Gumroad product URL
6. Replace `https://gumroad.com/l/YOURLINK` in README.md with your real URL
7. Push the updated README

---

## STEP 4 — Fulfillment (when someone buys)

**Via BTC:** When someone emails zenlightbulb@gmail.com with proof of payment:
1. Go to github.com/kron777/Nex_v4.0 → Settings → Collaborators
2. Click **"Add people"** → enter their GitHub username
3. They'll get an invite to access the private repo

**Via Gumroad:** Gumroad emails you when someone buys. Do the same as above.

---

## STEP 5 — Optional: Promote It

- Post about it on Mastodon/Discord (ironic — use NEX itself to promote NEX)
- Share the GitHub repo link (it'll show the README with the buy button)
- Post in AI/automation communities on Reddit (r/MachineLearning, r/artificial, r/selfhosted)

---

You're done. Every sale = someone emails you → you add them as a GitHub collaborator.
