# PixPress

**Resize photos, print passport photo sheets and work with PDFs. Everything runs on your computer.**

PixPress opens in your web browser, but nothing is uploaded anywhere. All processing happens locally.

| Tab | What it does |
|---|---|
| 🖼️ **Bulk Resize** | Resize hundreds of images at once to JPG / PNG / WebP, set DPI, and cap the file size (e.g. *under 200 KB* for online forms) |
| 🪪 **Passport Photos** | Print-ready PDF sheets with several copies of each photo (Nepal/India/UK/EU, US, China, Canada, custom sizes). Accepts photos **or PDFs** (each page becomes a photo, white borders trimmed) and has a **drag-to-crop tool**: drag/resize a box locked to the photo size, then save it per photo |
| 📄 **PDF Tools** | **Merge** PDFs and images (any mix) into one PDF · **Compress** to a level or a target size in MB · **Split & organize** (extract, remove, reorder, rotate pages) · **PDF → images** · **Add / remove password** |

---

## ⬇️ Download (no installation)

Get the latest version from the [**Releases**](../../releases/latest) page:

| Your computer | Download |
|---|---|
| Windows 10/11 | `PixPress-Windows-x64.exe` |
| Mac with Apple Silicon (M1–M4) | `PixPress-macOS-arm64.dmg` |
| Mac with Intel | `PixPress-macOS-x64.dmg` |
| Linux | `PixPress-Linux-x64` |

**Windows:** double-click the `.exe`. If you see *"Windows protected your PC"*, click **More info → Run anyway**. This shows up because the app isn't code-signed.

**Mac:** open the `.dmg` and drag **PixPress** onto **Applications**. The first time you open it:
- right-click PixPress → **Open**, or
- if macOS blocks it, go to **System Settings → Privacy & Security** and click **Open Anyway**.

If macOS says the app is *damaged*, run this once in Terminal: `xattr -cr /Applications/PixPress.app`

**Linux:** `chmod +x PixPress-Linux-x64 && ./PixPress-Linux-x64`

The app opens in your browser. To stop it, click **⏻ Quit app** at the bottom of the page.

---

## 🧑‍💻 Run from source

**Easiest:** double-click **`Start PixPress.command`** (macOS/Linux) or **`Start PixPress.bat`** (Windows).
On the first run it sets up a Python environment and installs everything. After an update it installs any new dependencies.

**Manual:**

```bash
python3 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
python app.py                     # browser opens automatically
```

Options (environment variables):

| Variable | Default | Purpose |
|---|---|---|
| `PIXPRESS_PORT` | first free port from 7860 | Fixed port |
| `PIXPRESS_HOST` | `127.0.0.1` | Set to `0.0.0.0` to use PixPress from other devices on your network |

### Optional speed-ups

- **pyvips** gives 5–10× faster bulk JPG resizing. Install the libvips system library first (`brew install vips`, `sudo apt install libvips-dev`), then `pip install pyvips`.
- **PyTorch GPU** (NVIDIA CUDA / Apple Metal): run `pip install torch` (NVIDIA: add `--index-url https://download.pytorch.org/whl/cu121`). GPU choices then appear under *Advanced options*.

---

## 📄 PDF Tools

- **Merge & Images → PDF.** Drop PDFs and images (JPG, PNG, WebP, TIFF, BMP, GIF) in any mix. Sort them by name or type a custom order such as `3, 1, 2`. Image pages can be A4 / Letter / Legal / A5 (auto portrait/landscape) or sized to each image.
- **Compress.** Choose *Light*, *Balanced* or *Strong*, or enter a **target size in MB**. PixPress then tries lighter settings first and stops as soon as the file fits. Compression shrinks the photos and scans inside the PDF. Text and vector graphics stay sharp.
- **Split & Organize.** Page syntax: `1-3, 5, 8-end`. You can keep pages (in your order), remove pages, split each range into its own PDF, or split every page. Pages can also be rotated.
- **PDF → Images.** Saves each page as a JPG or PNG at 72–600 DPI.
- **Password.** Add AES-256 password protection, or remove it if you know the password.

## 🪪 Passport Photos

1. Add one or more photos (one per person). **PDFs work too** — every page becomes a photo and the white page borders are trimmed automatically (turn this off under *Layout options*).
2. *(Optional)* In **✂️ Crop photos**, pick a photo (or click its thumbnail). **Drag the box** to move it and drag a **corner** (or scroll) to resize it — only what's inside the box is printed, and the box always has the shape of the chosen photo size. Keep the face in the oval guide and click **💾 Save crop**. The app remembers each photo's crop, marks it *✂️ cropped* and tells you the print quality (DPI). **Rotate 90°** and **Reset** are there too.
3. Pick a photo size preset or a custom size in mm, and the number of copies of each photo.
4. Pick the paper (A4, Letter, A5, Legal, 4×6″, 5×7″) and orientation. A live summary shows how many photos fit per page.
5. Click **Create Printable PDF**, check the preview, then download.

> **When printing, choose "Actual size" / 100 % scale.** "Fit to page" shrinks the photos.

---

## 🛠️ Development

```
app.py               entry point
pixpress/
  imaging.py         bulk resize engine (Pillow / pyvips / PyTorch)
  passport.py        passport sheet layout + PDF
  pdf_tools.py       merge, compress, organize, PDF→images, passwords
  ui.py              Gradio interface
  common.py          temp files, zips, helpers
assets/make_icon.py  generates the app icon
build.py             builds the standalone app for the current OS
tests/               pytest suite
```

```bash
pip install pytest && pytest -q     # run tests
python build.py                     # build dist/PixPress-<OS>-<arch>(.exe|.dmg)
```

### Releasing

GitHub Actions runs the tests on every push. Pushing a version tag builds Windows, macOS (Apple Silicon + Intel) and Linux apps and publishes them as a GitHub Release:

```bash
git tag v2.2.0
git push origin v2.2.0
```

You can also build without releasing: **Actions → Test, Build & Release → Run workflow**. The files appear as downloadable artifacts on that run.
