import { createRoot } from 'react-dom/client';
import App from './App.tsx';
import './styles.css';
import { initTheme } from './ui.tsx';

initTheme();
createRoot(document.getElementById('root')!).render(<App />);
