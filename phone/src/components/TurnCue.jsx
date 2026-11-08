// Brief Google Maps-style turn banner while evacuating.

import { TurnArriveIcon, TurnLeftIcon, TurnRightIcon, TurnSlightLeftIcon, TurnSlightRightIcon, TurnUturnIcon } from './icons.jsx'

const ICONS = {
  left: TurnLeftIcon,
  right: TurnRightIcon,
  'slight-left': TurnSlightLeftIcon,
  'slight-right': TurnSlightRightIcon,
  uturn: TurnUturnIcon,
  arrive: TurnArriveIcon,
}

export default function TurnCue({ cue }) {
  if (!cue) return null
  const Icon = ICONS[cue.kind] ?? TurnRightIcon
  return (
    <div className="turn-cue" role="status" aria-live="polite">
      <span className="turn-cue-icon" aria-hidden="true">
        <Icon size={36} />
      </span>
      <span className="turn-cue-text">
        <strong>{cue.instruction}</strong>
        <span className="num">{cue.distanceLabel}</span>
      </span>
    </div>
  )
}
