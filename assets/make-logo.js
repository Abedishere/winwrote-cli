// Generates assets/logo.svg: pixel block letters, yellow->orange gradient, outlined offset shadow.
// Run: node assets/make-logo.js
const fs = require('fs'), path = require('path');
const FONT = { // 5x7, '#' = block
  P: ['####.', '#...#', '#...#', '####.', '#....', '#....', '#....'],
  L: ['#....', '#....', '#....', '#....', '#....', '#....', '#####'],
  A: ['.###.', '#...#', '#...#', '#####', '#...#', '#...#', '#...#'],
  Y: ['#...#', '#...#', '.#.#.', '..#..', '..#..', '..#..', '..#..'],
  W: ['#...#', '#...#', '#...#', '#.#.#', '#.#.#', '##.##', '#...#'],
  R: ['####.', '#...#', '#...#', '####.', '#.#..', '#..#.', '#...#'],
  O: ['.###.', '#...#', '#...#', '#...#', '#...#', '#...#', '.###.'],
  T: ['#####', '..#..', '..#..', '..#..', '..#..', '..#..', '..#..'],
  E: ['#####', '#....', '#....', '####.', '#....', '#....', '#####'],
  I: ['#####', '..#..', '..#..', '..#..', '..#..', '..#..', '#####'],
  N: ['#...#', '##..#', '#.#.#', '#..##', '#...#', '#...#', '#...#'],
};
const word = process.argv[2] || 'WINWROTE', S = 18, GAP = 1, OFF = 6, PAD = 4;
const cells = [];
[...word].forEach((ch, i) => FONT[ch].forEach((row, y) => [...row].forEach((c, x) => {
  if (c === '#') cells.push([PAD + (i * (5 + GAP) + x) * S, PAD + y * S]);
})));
const W = PAD * 2 + (word.length * (5 + GAP) - GAP) * S + OFF + 2, H = PAD * 2 + 7 * S + OFF + 2;
const rect = (x, y, extra) => `<rect x="${x}" y="${y}" width="${S}" height="${S}" ${extra}/>`;
const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}">
<defs><linearGradient id="g" x1="0" y1="0" x2="0" y2="1">
<stop offset="0" stop-color="#f7d031"/><stop offset="0.5" stop-color="#f5a623"/><stop offset="1" stop-color="#ef6c2b"/>
</linearGradient></defs>
<g fill="none" stroke="#ef7a2b" stroke-width="1.6">${cells.map(([x, y]) => rect(x + OFF, y + OFF, '')).join('')}</g>
<g fill="url(#g)" stroke="url(#g)" stroke-width="0.6">${cells.map(([x, y]) => rect(x, y, '')).join('')}</g>
</svg>
`;
fs.writeFileSync(path.join(__dirname, 'logo.svg'), svg);
console.log('logo.svg', W, 'x', H, cells.length, 'blocks');
