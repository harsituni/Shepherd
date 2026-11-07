import { useState } from 'react'

const TIPS = {
  wildfire: [
    ["Leave as soon as you're told to", "Don't wait to see flames. Roads close fast."],
    ['Grab your go-bag', 'ID, medications, phone charger, water, pet supplies.'],
    ['Drive with lights on, windows up', 'Set air to recirculate to keep smoke out.'],
    ['Follow the route, not the crowd', 'Your route avoids where the fire is heading.'],
    ['Smoke is thick? Stay low', 'Cover your nose and mouth with a damp cloth.'],
  ],
  flood: [
    ['Move to higher ground', "Leave low-lying areas and river valleys before water rises."],
    ["Don't drive through water", '30 cm of moving water can float a car.'],
    ['Avoid walking in floodwater', 'It can hide debris, open drains and live wires.'],
    ['Turn off power if water enters', 'Only if you can reach the panel while standing somewhere dry.'],
    ['Follow the route, not the crowd', 'Your route avoids flooded and closed roads.'],
  ],
}

export default function TipsTab() {
  const [kind, setKind] = useState('wildfire')
  return (
    <div className="tips">
      <div className="segmented" role="group" aria-label="Hazard type">
        {[
          ['wildfire', 'Wildfire'],
          ['flood', 'Flood'],
        ].map(([v, label]) => (
          <button key={v} type="button" aria-pressed={kind === v} onClick={() => setKind(v)}>
            {label}
          </button>
        ))}
      </div>
      <ol className="list list-numbered">
        {TIPS[kind].map(([title, body]) => (
          <li key={title}>
            <strong>{title}</strong>
            <span>{body}</span>
          </li>
        ))}
      </ol>
    </div>
  )
}
