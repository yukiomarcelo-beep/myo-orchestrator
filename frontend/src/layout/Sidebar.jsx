import { useState } from 'react';

const navItems = [
  { label: 'Overview',      href: '/',                   icon: '◈' },
  { label: 'Analytics',     href: '/relatorios',          icon: '◉' },
  { label: 'Intelligence',  href: '/intelligence',        icon: '◎' },
  { label: 'Operations',    href: '/operacao',            icon: '◷' },
  { label: 'Alerts',        href: '/alertas',             icon: '◬' },
  { label: 'CRM',           href: '/crm',                 icon: '◈' },
  { label: 'Portfolio',     href: '/portfolio',           icon: '◉' },
  { label: 'ROI',           href: '/roi',                 icon: '◎' }
];

export function Sidebar() {
  const [active, setActive] = useState('/');

  return (
    <aside className="w-56 bg-[#0a0f1e] border-r border-[#1f2a44] flex flex-col p-4 flex-shrink-0">
      <div className="mb-8">
        <h1 className="text-lg font-black tracking-widest text-white">MYO</h1>
        <p className="text-[10px] text-gray-600 uppercase tracking-widest">OS v3</p>
      </div>

      <nav className="flex-1 flex flex-col gap-0.5">
        {navItems.map(item => (
          <a
            key={item.href}
            href={item.href}
            onClick={() => setActive(item.href)}
            className={`flex items-center gap-2.5 px-3 py-2 rounded-lg text-sm transition-all
              ${active === item.href
                ? 'bg-violet-600/15 text-violet-300 font-medium'
                : 'text-gray-500 hover:text-gray-300 hover:bg-white/4'
              }`}
          >
            <span className="text-xs opacity-60">{item.icon}</span>
            {item.label}
          </a>
        ))}
      </nav>

      <div className="border-t border-[#1f2a44] pt-4 text-[10px] text-gray-700">
        MYO OS — Engine v1
      </div>
    </aside>
  );
}
