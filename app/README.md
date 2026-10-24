# Unstep Pilot App

The phone screen for pilots in the live room. Static build, talks to the hub (`python -m unstep.live`) over `/live/ws`.

```
npm install
npm run dev      # http://localhost:5173/?hub=http://localhost:8765
npm test
npm run build    # dist/, served by the hub at /pilot/ or deployed to Vercel
```

The hub address comes from the join link: `?hub=<host or URL>&token=<room token>`. Served by the hub itself, no parameters are needed. Hosting steps: [docs/15-pilot-app-and-sponsor-plan.md](../docs/15-pilot-app-and-sponsor-plan.md#2-hosting-for-the-demo).
