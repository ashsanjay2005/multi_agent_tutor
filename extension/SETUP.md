# Chrome Extension Setup Guide

Complete setup instructions for the AI Math Tutor Chrome Extension.

## 📋 Prerequisites

1. **Node.js 18+** installed
2. **Backend server** running at `http://localhost:8000`
3. **Chrome browser** (or Chromium-based browser)

## 🚀 Step-by-Step Setup

### 1. Install Dependencies

```bash
cd extension
npm install
```

This installs:
- React 18
- TypeScript
- Vite
- Tailwind CSS
- Lucide icons
- DOMPurify
- All dev dependencies

### 2. Create Extension Icons (Optional)

The extension needs three icon sizes. Create simple icons or use placeholders:

```bash
# In extension/public/icons/
# Add: icon-16.png, icon-48.png, icon-128.png
```

**Quick Placeholder Icons:**
You can use any 16x16, 48x48, and 128x128 PNG images as placeholders. The extension will work without them (Chrome shows a default icon).

### 3. Build the Extension

```bash
npm run build
```

This creates a `dist/` folder with:
- `manifest.json`
- `popup.html`
- `popup.js` (bundled React app)
- `popup.css` (bundled styles)
- `icons/` (if present)

### 4. Load Extension in Chrome

1. Open Chrome and go to `chrome://extensions/`
2. Enable **"Developer mode"** (toggle in top-right corner)
3. Click **"Load unpacked"**
4. Navigate to `extension/dist/` folder and select it
5. The extension icon should appear in your toolbar

### 5. Pin the Extension (Recommended)

1. Click the puzzle piece icon in Chrome toolbar
2. Find "AI Math Tutor"
3. Click the pin icon to keep it visible

## ✅ Verify Installation

### Test Backend Connection

1. Make sure backend is running:
```bash
cd ../backend
poetry run python main.py
# Should be running on http://localhost:8000
```

2. Click the extension icon
3. You should see the "Paste Text" and "Screenshot" tabs
4. No connection errors should appear

### Test Text Analysis

1. Click extension icon
2. Go to "Paste Text" tab
3. Enter: `Solve: 2x + 5 = 13`
4. Click "Solve Problem"
5. Should see loading spinner, then results

### Test Screenshot Capture

1. Open a webpage with math content
2. Click extension icon
3. Go to "Screenshot" tab
4. Click "Capture & Solve"
5. Should capture and analyze the page

## 🔧 Development Workflow

### Making Changes

1. Edit files in `src/`
2. Rebuild: `npm run build`
3. Go to `chrome://extensions/`
4. Click "Reload" icon on the extension card
5. Test changes by clicking the extension icon

### Hot Reload (Alternative)

For faster development, you can run the dev server:

```bash
npm run dev
```

Then open `http://localhost:5173` in your browser. This gives you hot reload, but you'll need to manually test Chrome Extension-specific features (like screenshot capture).

### Type Checking

```bash
npm run type-check
```

## 📁 Project Structure

```
extension/
├── public/
│   └── icons/              # Extension icons
├── src/
│   ├── components/
│   │   ├── ui/             # Shadcn/UI base components
│   │   │   ├── button.tsx
│   │   │   ├── tabs.tsx
│   │   │   ├── card.tsx
│   │   │   ├── textarea.tsx
│   │   │   ├── radio-group.tsx
│   │   │   └── alert.tsx
│   │   ├── LoadingView.tsx       # Loading spinner
│   │   ├── DisambiguationView.tsx # Topic selection
│   │   └── SolutionView.tsx       # Solution display
│   ├── lib/
│   │   ├── api.ts          # Backend API client
│   │   ├── types.ts        # TypeScript types
│   │   └── utils.ts        # Helper functions
│   ├── App.tsx             # Main app logic
│   ├── main.tsx            # Entry point
│   └── index.css           # Global styles
├── dist/                   # Build output (created by npm run build)
├── manifest.json           # Extension manifest
├── popup.html              # Popup HTML
├── vite.config.ts          # Vite config
├── tailwind.config.js      # Tailwind config
├── tsconfig.json           # TypeScript config
└── package.json            # Dependencies
```

## 🎨 Customization

### Change Backend URL

Edit `src/lib/api.ts`:

```typescript
const API_BASE_URL = 'https://your-backend-url.com';
```

Then update `manifest.json` `host_permissions`:

```json
{
  "host_permissions": [
    "https://your-backend-url.com/*"
  ]
}
```

### Change Color Theme

Edit `src/index.css` CSS variables:

```css
:root {
  --primary: 217.2 91.2% 59.8%;  /* Blue */
  --background: 222.2 84% 4.9%;  /* Dark slate */
  /* ... */
}
```

### Change Popup Size

Edit `popup.html`:

```html
<body class="w-[450px] h-[600px]">
```

## 🐛 Troubleshooting

### Build Errors

**Error: `Cannot find module`**
```bash
rm -rf node_modules package-lock.json
npm install
```

**TypeScript errors**
```bash
npm run type-check
```

### Extension Won't Load

**Check manifest.json exists in dist/**
```bash
ls dist/manifest.json
# Should exist after npm run build
```

**Check for manifest errors**
- Chrome shows error message when loading
- Common: Missing required fields, invalid permissions

### API Calls Failing

**CORS errors:**
- Backend must allow `chrome-extension://*` origin
- Or disable CORS for development

**Connection refused:**
```bash
# Check backend is running
curl http://localhost:8000/health

# Should return: {"status":"healthy",...}
```

**Host permissions denied:**
- Check `manifest.json` has correct `host_permissions`
- Reload extension after changing manifest

### Screenshot Not Working

**Permission denied:**
- Extension needs `activeTab` permission (already in manifest)
- Cannot capture `chrome://` or `chrome-extension://` pages

**Black/blank screenshot:**
- Some pages block screenshot capture (DRM content)
- Try a different webpage

## 📦 Building for Production

1. **Update manifest version:**
```json
{
  "version": "1.0.0"
}
```

2. **Change backend URL** (see Customization above)

3. **Build:**
```bash
npm run build
```

4. **Create .zip for Chrome Web Store:**
```bash
cd dist
zip -r ../extension-v1.0.0.zip .
```

5. **Upload to [Chrome Web Store](https://chrome.google.com/webstore/devconsole/)**

## 🔒 Security Notes

- All HTML from backend is sanitized with DOMPurify
- CSP (Content Security Policy) is enforced
- No inline scripts allowed
- API calls require explicit host permissions

## 📚 Additional Resources

- [Chrome Extension Docs](https://developer.chrome.com/docs/extensions/)
- [Manifest V3 Migration](https://developer.chrome.com/docs/extensions/mv3/intro/)
- [Vite Docs](https://vitejs.dev/)
- [Tailwind CSS Docs](https://tailwindcss.com/)
- [React Docs](https://react.dev/)

## ✨ Next Steps

After successful setup:

1. Test all features (paste, screenshot, disambiguation)
2. Customize branding (icons, colors, name)
3. Add real LLM integration to backend (replace mocks)
4. Deploy backend to production
5. Update extension to use production URL
6. Publish to Chrome Web Store

---

**Need Help?** Check the main [README.md](./README.md) or the backend [README.md](../backend/README.md)


