import assert from 'node:assert/strict'
import {acceptsPlanSnapshot} from '../src/plan-snapshot.ts'

let shown = {session_id:'hubei',revision:33,draft:'original',adopted:null}
const apply = next => {if(acceptsPlanSnapshot(shown,next))shown=next}
let finishOldRead
const oldRead = new Promise(resolve=>{finishOldRead=resolve}).then(apply)
// The ordinary preview POST finishes before the read it overlapped.
apply({session_id:'hubei',revision:34,draft:'seven-day-preview',adopted:null})
finishOldRead({session_id:'hubei',revision:33,draft:'original',adopted:null})
await oldRead
assert.equal(shown.revision,34,'adoption must use the saved preview revision')
assert.equal(shown.draft,'seven-day-preview','late polling must not restore the pre-preview form')
apply({session_id:'hubei',revision:35,draft:'seven-day-preview',adopted:'seven-day-preview'})
apply({session_id:'hubei',revision:34,draft:'seven-day-preview',adopted:null})
assert.equal(shown.adopted,'seven-day-preview','late polling must not undo displayed adoption')
apply({session_id:'hubei',revision:35,draft:'seven-day-preview',adopted:'seven-day-preview',progress:'complete'})
assert.equal(shown.progress,'complete','same-revision progress updates remain visible')
apply({session_id:'wuhan',revision:1,draft:'city',adopted:null})
assert.equal(shown.session_id,'wuhan','switching to a different trip permits its own revision')
assert(acceptsPlanSnapshot(null,shown))
console.log('PASS planning snapshots: delayed reads cannot revert preview/adoption; progress and trip switching remain available')
