import { createRoot } from 'react-dom/client';
import App from './App.tsx';
import { StoreErrorBoundary } from './ErrorBoundary.tsx';
import '@melorin/web-kit/tokens.css';
import './styles.css';
import { initTheme } from './ui.tsx';

initTheme();
createRoot(document.getElementById('root')!).render(
  <StoreErrorBoundary>
    <App />
  </StoreErrorBoundary>,
);
