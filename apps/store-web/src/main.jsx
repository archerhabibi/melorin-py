import React from 'react';
import { createRoot } from 'react-dom/client';
import App from './App.jsx';
import './styles.css';
import { initTheme } from './ui.jsx';

initTheme();
createRoot(document.getElementById('root')).render(<App />);
