import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App.tsx';
import './index.css';

// Use 100vh for side panel, min-height for popup fallback
ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <div className="dark min-h-[600px] h-screen overflow-y-auto">
      <App />
    </div>
  </React.StrictMode>
);
