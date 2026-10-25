# The control tower console on Vercel, with the compute on Render

Second Vercel project (the first is the pilot app in `app/`). It holds no code: its `vercel.json` forwards the console
page and everything under `/live/` (the 3D models, scripts, QR image, `GET`/`POST` calls) to the Render hub.
A WebSocket cannot pass through a Vercel rewrite, so the page, which the hub fills in with its own address
(`UNSTEP_PUBLIC_URL`), opens the socket straight to Render.

Set up (once, in the Vercel dashboard):
1. New Project, import this repo, **Root Directory `deploy/console`**, Framework Other, name it **`cagent-console`**
   (the hub already allows every `cagent*.vercel.app` and `*-dee-1862s-projects.vercel.app` address for sockets).
2. Deploy. Open `https://cagent-console.vercel.app/`.
3. If your Render service is not `unstep.onrender.com`, change the two destinations in `vercel.json`.

On Render set `UNSTEP_PUBLIC_URL` (already `https://unstep.onrender.com` in `render.yaml`) and `UNSTEP_PILOT_APP_URL` to
the pilot app's Vercel address so the QR code on the console points at it. If `UNSTEP_ATC_PASSWORD` is set, the console
asks for it as before.

Limits: Render's free plan sleeps after about 15 minutes idle and takes about a minute to wake; the first load after that
is slow. Everything the console shows still comes from `master`'s deploy on Render, so Render has to deploy the branch
that has these files.
