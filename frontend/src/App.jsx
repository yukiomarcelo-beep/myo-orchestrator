import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import Dashboard   from './pages/Dashboard';
import Operations  from './pages/Operations';
import './index.css';

export default function App() {
  return (
    <BrowserRouter basename="/app">
      <Routes>
        <Route path="/"          element={<Dashboard />} />
        <Route path="/operacao"  element={<Operations />} />
        <Route path="*"          element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  );
}
