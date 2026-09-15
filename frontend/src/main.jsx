import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';
import './index.css';

// Render App directly without StrictMode double-mounting in dev
ReactDOM.createRoot(document.getElementById('root')).render(
  <App />
);
