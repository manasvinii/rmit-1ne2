import Icon from './Icon'

const COLORS = { E: 'var(--teal)', S: 'var(--amber)', G: 'var(--red)' }

/**
 * Status marker that never relies on colour alone:
 * E → ✓ (teal)   S → ~ (amber)   G → ! (red)   N/todo → dashed empty circle
 */
export default function StatusIcon({ status, size = 26, square = false }) {
  const box = { width: size, height: size, flex: `0 0 ${size}px` }
  if (!COLORS[status]) return <span className="dot-empty" style={box} aria-hidden="true" />
  return (
    <span
      className="sicon"
      aria-hidden="true"
      style={{
        ...box,
        borderRadius: square ? Math.round(size / 3) : '50%',
        background: COLORS[status],
        fontSize: Math.round(size * 0.55),
      }}
    >
      {status === 'E' ? <Icon name="check" size={Math.round(size * 0.5)} stroke={3.5} /> : status === 'S' ? '~' : '!'}
    </span>
  )
}
