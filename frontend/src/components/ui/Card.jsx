export function Card({ children, className = '' }) {
  return (
    <div className={`bg-[#111633] border border-[#1f2a44] rounded-xl p-4 ${className}`}>
      {children}
    </div>
  );
}
