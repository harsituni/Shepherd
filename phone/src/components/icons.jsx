// Simple inline stroke icons (no emoji, no icon library).

function Svg({ size = 18, strokeWidth = 2, children, style, className }) {
  return (
    <svg
      className={className}
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={strokeWidth}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      style={style}
    >
      {children}
    </svg>
  )
}

// Placeholder logo: a shepherd's crook (matches the dashboard's mark).
export const CrookIcon = (p) => (
  <Svg strokeWidth={2.2} {...p}>
    <path d="M7 21V9a5 5 0 0 1 10 0" />
    <path d="M17 9v2" />
    <path d="M4 21h16" />
  </Svg>
)

export const WarningIcon = (p) => (
  <Svg size={20} {...p}>
    <path d="M12 3 2 20h20L12 3z" />
    <path d="M12 10v4M12 17h.01" />
  </Svg>
)

export const InfoIcon = (p) => (
  <Svg size={20} {...p}>
    <circle cx="12" cy="12" r="9" />
    <path d="M12 11v5M12 8h.01" />
  </Svg>
)

export const RerouteIcon = (p) => (
  <Svg size={16} {...p}>
    <path d="M4 7h11a5 5 0 0 1 0 10H9" />
    <path d="m8 3-4 4 4 4" />
  </Svg>
)

export const TurnIcon = (p) => (
  <Svg size={22} {...p}>
    <path d="M9 18V8h9" />
    <path d="m14 4 4 4-4 4" />
  </Svg>
)

export const PinIcon = (p) => (
  <Svg size={18} {...p}>
    <path d="M12 21s-7-6.2-7-11a7 7 0 0 1 14 0c0 4.8-7 11-7 11z" />
    <circle cx="12" cy="10" r="2.5" />
  </Svg>
)

export const CloseIcon = (p) => (
  <Svg size={18} {...p}>
    <path d="M6 6l12 12M18 6 6 18" />
  </Svg>
)

// Map screen controls.
export const BellIcon = (p) => (
  <Svg size={20} {...p}>
    <path d="M6 16V11a6 6 0 0 1 12 0v5l1.5 2h-15L6 16z" />
    <path d="M10 20.5a2 2 0 0 0 4 0" />
  </Svg>
)

export const CheckIcon = (p) => (
  <Svg size={20} {...p}>
    <path d="m5 12.5 4.5 4.5L19 7.5" />
  </Svg>
)

export const ChevronUpIcon = (p) => (
  <Svg size={18} {...p}>
    <path d="m6 15 6-6 6 6" />
  </Svg>
)
