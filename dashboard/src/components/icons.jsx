// Simple inline stroke icons (no emoji, no icon library).

function Svg({ size = 18, strokeWidth = 2, children }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={strokeWidth}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {children}
    </svg>
  )
}

export const CrookIcon = () => (
  <Svg strokeWidth={2.2}>
    <path d="M7 21V9a5 5 0 0 1 10 0" />
    <path d="M17 9v2" />
    <path d="M4 21h16" />
  </Svg>
)

export const PauseIcon = () => (
  <Svg strokeWidth={2.4}>
    <path d="M8 5v14M16 5v14" />
  </Svg>
)

export const PlayIcon = () => (
  <Svg strokeWidth={2.2}>
    <path d="M7 4.5v15l12-7.5z" />
  </Svg>
)

export const ResetIcon = () => (
  <Svg>
    <path d="M3 12a9 9 0 1 0 3-6.7" />
    <path d="M3 4v5h5" />
  </Svg>
)

export const PlusIcon = () => (
  <Svg strokeWidth={2.2}>
    <path d="M12 5v14M5 12h14" />
  </Svg>
)

export const CloseIcon = () => (
  <Svg strokeWidth={2.2}>
    <path d="M6 6l12 12M18 6L6 18" />
  </Svg>
)

export const MinusIcon = () => (
  <Svg strokeWidth={2.2}>
    <path d="M5 12h14" />
  </Svg>
)
