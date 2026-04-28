import { NavLink } from 'react-router-dom';

const navItems = [
  { label: 'Dashboard',    to: '/',             icon: '◈' },
  { label: 'Operação',     to: '/operacao',     icon: '◷' },
  { label: 'Organograma',  href: '/organograma', icon: '◉', external: true },
  { label: 'Relatórios',   href: '/relatorios',  icon: '◎', external: true },
  { label: 'Carteira',     href: '/carteira',    icon: '◈', external: true },
  { label: 'ROI',          href: '/roi',         icon: '◎', external: true },
  { label: 'CRM',          href: '/crm',         icon: '◈', external: true },
  { label: 'Vendas',       href: '/vendas',      icon: '◉', external: true },
  { label: 'Produtos',     href: '/produtos',    icon: '◎', external: true },
];

const cls = (active) =>
  `flex items-center gap-2.5 px-3 py-2 rounded-lg text-sm transition-all ${
    active
      ? 'bg-violet-600/15 text-violet-300 font-medium'
      : 'text-gray-500 hover:text-gray-300 hover:bg-white/5'
  }`;

export function Sidebar() {
  return (
    <aside className="w-52 bg-[#0a0f1e] border-r border-[#1f2a44] flex flex-col py-4 px-3 flex-shrink-0">
      <div className="px-2 mb-6">
        <h1 className="text-base font-black tracking-widest text-white">MYO</h1>
        <p className="text-[9px] text-gray-600 uppercase tracking-widest">OS v3</p>
      </div>

      <nav className="flex-1 flex flex-col gap-px">
        {navItems.map(item =>
          item.external ? (
            <a
              key={item.href}
              href={item.href}
              className={cls(false)}
            >
              <span className="text-[10px] opacity-50">{item.icon}</span>
              {item.label}
            </a>
          ) : (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === '/'}
              className={({ isActive }) => cls(isActive)}
            >
              <span className="text-[10px] opacity-50">{item.icon}</span>
              {item.label}
            </NavLink>
          )
        )}
      </nav>

      <div className="border-t border-[#1f2a44] pt-3 px-2 text-[9px] text-gray-700 uppercase tracking-widest">
        Engine v1
      </div>
    </aside>
  );
}
