# web/

React + SmoothUI front end for the approval UI. See the README one level up for setup.

```bash
npm install --legacy-peer-deps
npm run build    # output in dist/, served by `python -m incident_ui`
npm run dev      # live reload on :5173, proxies /api to the server on :8502
```

- `src/api.ts`: every call to the server, and the JSON types it returns
- `src/describe.ts`: plain-language wording (tool steps, actions, status, confidence)
- `src/Thread.tsx`: the chat thread; `src/App.tsx`: layout, header, side panel
