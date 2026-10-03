/*
 * The three AI students, drawn as inline SVG so they scale cleanly.
 * <PersonaAvatar id="pip" size={120} mood="puzzled" onDark />
 */

function Pip({ size, mood = 'curious', onDark, label }) {
  const puzzled = mood === 'puzzled'
  return (
    <svg width={size} height={size} viewBox="0 0 120 120" role={label ? 'img' : undefined} aria-label={label} aria-hidden={label ? undefined : true}>
      <path d="M60 8 C58 -2 70 -2 68 6" stroke={onDark ? '#D4F74A' : '#9BBF1E'} strokeWidth="4.5" fill="none" strokeLinecap="round" />
      <circle cx="60" cy="62" r="52" fill="#D4F74A" />
      <circle cx="43" cy="56" r="11" fill="#FFFFFF" />
      <circle cx="77" cy="56" r="11" fill="#FFFFFF" />
      {puzzled ? (
        <>
          <circle cx="46" cy="53" r="5.5" fill="#15161B" />
          <circle cx="80" cy="53" r="5.5" fill="#15161B" />
          <path d="M32 36 L50 40" stroke="#15161B" strokeWidth="3.5" strokeLinecap="round" />
          <path d="M70 34 L88 30" stroke="#15161B" strokeWidth="3.5" strokeLinecap="round" />
          <path d="M48 86 Q54 80 60 86 T72 86" stroke="#15161B" strokeWidth="4" fill="none" strokeLinecap="round" />
        </>
      ) : (
        <>
          <circle cx="45" cy="58" r="5.5" fill="#15161B" />
          <circle cx="79" cy="58" r="5.5" fill="#15161B" />
          <path d="M33 40 L50 37" stroke="#15161B" strokeWidth="3.5" strokeLinecap="round" />
          <path d="M70 36 L87 41" stroke="#15161B" strokeWidth="3.5" strokeLinecap="round" />
          <ellipse cx="60" cy="84" rx="7" ry="8" fill="#15161B" />
        </>
      )}
    </svg>
  )
}

function Sage({ size, label }) {
  return (
    <svg width={size} height={size} viewBox="0 0 120 120" role={label ? 'img' : undefined} aria-label={label} aria-hidden={label ? undefined : true}>
      <rect x="8" y="10" width="104" height="104" rx="30" fill="#9CC0FF" />
      <circle cx="42" cy="56" r="14" fill="#FFFFFF" stroke="#15161B" strokeWidth="4" />
      <circle cx="78" cy="56" r="14" fill="#FFFFFF" stroke="#15161B" strokeWidth="4" />
      <path d="M56 56 H64" stroke="#15161B" strokeWidth="4" />
      <circle cx="42" cy="58" r="5" fill="#15161B" />
      <circle cx="78" cy="58" r="5" fill="#15161B" />
      <path d="M30 34 L52 38" stroke="#15161B" strokeWidth="4" strokeLinecap="round" />
      <path d="M68 38 L90 34" stroke="#15161B" strokeWidth="4" strokeLinecap="round" />
      <path d="M48 88 H72" stroke="#15161B" strokeWidth="4.5" strokeLinecap="round" />
    </svg>
  )
}

function Milo({ size, label }) {
  return (
    <svg width={size} height={size} viewBox="0 0 120 120" role={label ? 'img' : undefined} aria-label={label} aria-hidden={label ? undefined : true}>
      <path d="M20 60 C14 28 44 10 66 14 C96 18 112 44 104 72 C96 100 70 112 46 106 C26 100 24 82 20 60 Z" fill="#FFA27F" />
      <circle cx="44" cy="54" r="12" fill="#FFFFFF" />
      <circle cx="78" cy="58" r="8" fill="#FFFFFF" />
      <circle cx="47" cy="52" r="5.5" fill="#15161B" />
      <circle cx="76" cy="60" r="4" fill="#15161B" />
      <path d="M44 84 Q52 78 60 84 T76 84" stroke="#15161B" strokeWidth="4" fill="none" strokeLinecap="round" />
      <path d="M94 18 Q102 10 108 18 Q112 26 102 30 L101 36" stroke="#15161B" strokeWidth="4" fill="none" strokeLinecap="round" />
      <circle cx="101" cy="44" r="2.8" fill="#15161B" />
    </svg>
  )
}

export function PersonaAvatar({ id = 'pip', size = 64, mood, onDark, label }) {
  if (id === 'sage') return <Sage size={size} label={label} />
  if (id === 'milo') return <Milo size={size} label={label} />
  return <Pip size={size} mood={mood} onDark={onDark} label={label} />
}
