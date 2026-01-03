# AI Math Tutor - Chrome Extension

React-based Chrome Extension (Manifest V3) that integrates with the AI Math Tutor backend.

## 🚀 Quick Start

### Prerequisites
- Node.js 18+ and npm/yarn
- Backend server running at `http://localhost:8000`

### Installation

1. **Install dependencies:**
```bash
npm install
# or
yarn install
```

2. **Build the extension:**
```bash
npm run build
```

This creates a `dist/` folder with the compiled extension.

3. **Load in Chrome:**
   - Open Chrome and navigate to `chrome://extensions/`
   - Enable "Developer mode" (top right toggle)
   - Click "Load unpacked"
   - Select the `dist/` folder

## 🛠️ Development

### Development Mode

```bash
npm run dev
```

This starts Vite's dev server. However, for Chrome Extension development, you'll need to:

1. Build the extension (`npm run build`)
2. Load it in Chrome
3. Make changes and rebuild
4. Click "Reload" in Chrome's extension management page

### Project Structure

```
extension/
├── public/
│   └── icons/              # Extension icons (16x16, 48x48, 128x128)
├── src/
│   ├── components/
│   │   ├── ui/             # Shadcn/UI components
│   │   ├── LoadingView.tsx
│   │   ├── DisambiguationView.tsx
│   │   └── SolutionView.tsx
│   ├── lib/
│   │   ├── api.ts          # Backend API client
│   │   ├── types.ts        # TypeScript types
│   │   └── utils.ts        # Utilities
│   ├── App.tsx             # Main application
│   ├── main.tsx            # Entry point
│   └── index.css           # Tailwind styles
├── manifest.json           # Chrome Extension manifest
├── popup.html              # Extension popup HTML
├── vite.config.ts          # Vite configuration
└── package.json
```

## 📋 Features

### ✅ Implemented

1. **Tabbed Interface:**
   - **Paste Tab**: Text input with textarea
   - **Screenshot Tab**: Capture visible tab content

2. **API Integration:**
   - `/v1/analyze` - Send text or image
   - `/v1/resume` - Resume after topic selection
   - `/v1/explain_step` - Get step explanations

3. **State Management:**
   - Loading view with spinner
   - Disambiguation view (topic selection)
   - Solution view (rendered HTML)
   - Error handling

4. **Step Explainer:**
   - Click on `.step-trigger` elements
   - Fetch explanation via API
   - Display in drawer

5. **UI/UX:**
   - Dark mode by default (Slate palette)
   - 450x600px popup dimensions
   - Tailwind CSS + Shadcn/UI components
   - Responsive design

## 🔌 Backend Integration

The extension expects the backend at `http://localhost:8000`.

### API Endpoints Used

#### POST `/v1/analyze`
```typescript
{
  type: "text" | "image",
  content: string,  // Text or base64 image (without prefix)
  user_id: string,
  thread_id?: string
}
```

#### POST `/v1/resume`
```typescript
{
  thread_id: string,
  selected_topic: string
}
```

#### POST `/v1/explain_step`
```typescript
{
  step_text: string,
  context: string,
  topic: string
}
```

## 🎨 Styling

Built with Tailwind CSS and custom CSS variables:

- **Primary**: Blue (HSL-based)
- **Background**: Dark slate
- **Foreground**: Light text
- **Muted**: Grayed elements

## 🔒 Permissions

The extension requires:

- `activeTab` - Access to current tab
- `scripting` - For future features
- `storage` - Store user preferences
- `host_permissions` - `http://localhost:8000/*` for API calls

## 📦 Building for Production

```bash
npm run build
```

For production deployment:

1. Update `manifest.json` to change `host_permissions` from localhost to your production URL
2. Build the extension
3. Package as `.crx` or upload to Chrome Web Store

## 🐛 Troubleshooting

### Extension won't load
- Make sure you've run `npm run build`
- Check that `dist/manifest.json` exists
- Verify all permissions in manifest.json

### API calls failing
- Ensure backend is running at `http://localhost:8000`
- Check `host_permissions` in manifest.json
- Open DevTools (right-click extension → Inspect) to see console errors

### Screenshot not working
- Verify `activeTab` permission is granted
- Make sure you're clicking from a valid tab (not chrome:// pages)

## 📝 Type Safety

The extension is fully typed with TypeScript. Types in `src/lib/types.ts` match the backend Pydantic models exactly.

## 🔗 Related Files

- Backend: `../backend/main.py`
- Architecture: `../ARCHITECTURE.md`
- Backend API Docs: `http://localhost:8000/docs` (when running)

## 🚧 Future Enhancements

- [ ] Offline support
- [ ] History/saved problems
- [ ] Custom keyboard shortcuts
- [ ] Multiple backend URLs
- [ ] Theme customization
- [ ] Export solutions as PDF

## 📄 License

[Your License Here]


