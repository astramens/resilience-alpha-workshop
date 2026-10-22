import credits from './photo-credits.json'
const mapping:Record<string,keyof typeof credits>={"prop-1.svg": "RP-PIS-001", "prop-2.svg": "RP-FUS-003", "prop-3.svg": "RP-ARB-001", "prop-4.svg": "RP-COU-002", "prop-5.svg": "RP-INE-001", "prop-6.svg": "RP-PIS-002", "prop-7.svg": "RP-FUS-004", "prop-8.svg": "RP-COU-002", "prop-9.svg": "RP-INE-002", "prop-10.svg": "RP-ARB-002", "prop-11.svg": "RP-PIS-001", "prop-12.svg": "RP-INE-001"}
export function photoCredit(image:string){const key=mapping[image];return key?credits[key]:undefined}
export function productImage(image:string){return '/products/'+(photoCredit(image)?.file||image)}
export {credits as photoCredits}
