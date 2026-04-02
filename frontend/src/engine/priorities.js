export const priorityMap = {
  critical: {
    border: 'border-red-500',
    text: 'text-red-400',
    bg: 'bg-red-500/10',
    label: 'bg-red-500/10 text-red-400 border border-red-500/20'
  },
  high: {
    border: 'border-yellow-500',
    text: 'text-yellow-400',
    bg: 'bg-yellow-500/10',
    label: 'bg-yellow-500/10 text-yellow-400 border border-yellow-500/20'
  },
  medium: {
    border: 'border-blue-500',
    text: 'text-blue-400',
    bg: 'bg-blue-500/10',
    label: 'bg-blue-500/10 text-blue-400 border border-blue-500/20'
  }
};

export const typeColorMap = {
  'OPORTUNIDADE': 'bg-green-500/10 text-green-400 border border-green-500/20',
  'ALERTA':       'bg-red-500/10 text-red-400 border border-red-500/20',
  'RECOMENDAÇÃO': 'bg-cyan-500/10 text-cyan-400 border border-cyan-500/20',
  'PADRÃO':       'bg-yellow-500/10 text-yellow-400 border border-yellow-500/20'
};
