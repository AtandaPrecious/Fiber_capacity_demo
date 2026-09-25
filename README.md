# Fiber Capacity Management – demo app

A working demo of the data standard (v3): colour-coded utilization, "who feeds me?" tracing,
coverage-checked requests, GIS approvals, installer confirmation, automatic alerts and a live
request & approval log.

**Sample data only.** Every change stays in your own browser session. Press *Reset demo* to start again.

## What's in the folder

| File | What it is |
| --- | --- |
| `app.py` | The app |
| `requirements.txt` | The Python packages Streamlit needs |
| `.streamlit/config.toml` | Colours and theme (matches the slides) |
| `data/*.csv` | One file per sheet in the standard: OLT, ODF, cabinets, FDTs, FATs, ONUs, cables, cable cores, POP / street / estate lists, plus demo addresses |

## Put it online for free (Streamlit Community Cloud)

You need a free GitHub account and a free Streamlit account. About 10 minutes.

1. **Create a GitHub repository**
   - Go to github.com, sign in, click **New** (green button), name it `fiber-capacity-demo`, choose **Private** or **Public**, and click **Create repository**.
2. **Upload the files**
   - On the new repository page, click **uploading an existing file**.
   - Drag in `app.py`, `requirements.txt`, `README.md` and the whole **`data`** folder. Click **Commit changes**.
   - The `.streamlit` folder is hidden on some computers. If it did not upload: click **Add file → Create new file**, type the name `.streamlit/config.toml`, paste the contents of that file, and click **Commit changes**. (The app still works without it; it just uses Streamlit's default colours.)
3. **Deploy**
   - Go to **share.streamlit.io** and sign in with GitHub.
   - Click **Create app** → **Deploy a public app from GitHub**.
   - Repository: `your-name/fiber-capacity-demo` · Branch: `main` · Main file path: `app.py`.
   - Optional: set a short App URL, for example `fiber-capacity-demo`.
   - Click **Deploy**. After a minute or two you get a link like `https://fiber-capacity-demo.streamlit.app`.
4. **Share it**
   - Send the link to your manager. For a private app, open the app's **Settings → Sharing** and add their email.

To update the app later, edit or re-upload the file on GitHub; the app refreshes by itself.

## Run it on your own computer instead

```
pip install -r requirements.txt
streamlit run app.py
```

It opens in your browser at http://localhost:8501.

## A 3-minute demo script

1. **Dashboard**: point out the red, orange and yellow banners, the map colours, and the log on the right (the warnings at 08:00 were raised automatically).
2. **Search and trace → Trace a customer**: the path from the customer up to the OLT, and the SmartOLT check.
3. **Who is affected?**: pick FAT-0145 and show that its chain takes FAT-0146 and FAT-0147 down with it.
4. **New request**: submit *18 Toyin Street*. The coverage checker says covered and the app suggests FATs.
5. Submit *7 Kudirat Road*: not covered, closed at once, added to the demand list.
6. Submit *40 Opebi Road*: covered, but FAT-0164 is refused because its chain is full (tightest point rule).
7. **GIS approvals**: approve the Toyin Street request. The port is held and the log shows the impact.
8. **Installer jobs**: try to confirm without a photo (blocked), then tick the photo and confirm. The FAT turns yellow and an early warning appears in the log.
9. **Data sheets**: show that it is all built on the simple sheets in the standard.

## Changing the rules

The numbers at the top of `app.py` control the demo: `SEARCH_RADIUS_M` (200 m), `COVERAGE_RADIUS_M`,
`HOLD_DAYS` (7), `GPS_LIMIT_M` (100). Colour thresholds are in `colour_of()`.
The coverage checker here is a stand-in (covered = a FAT or FDT within 250 m); the real app would call the company's coverage checker instead.
