import assert from 'node:assert/strict'
import {readCurrentTrip, rememberCurrentTrip} from '../src/current-trip.ts'

const storage = () => { const values = new Map(); return {getItem:key=>values.get(key)??null,setItem:(key,value)=>values.set(key,value)} }
globalThis.localStorage = storage()
const tabA = storage(), tabB = storage()
globalThis.sessionStorage = tabA
rememberCurrentTrip('hubei-running')
globalThis.sessionStorage = tabB
assert.equal(readCurrentTrip(), 'hubei-running')
rememberCurrentTrip('shanxi-history')
globalThis.sessionStorage = tabA
assert.equal(readCurrentTrip(), 'hubei-running', 'refresh of tab A must retain its ongoing trip')
rememberCurrentTrip('hubei-running') // polling in A must not switch B
globalThis.sessionStorage = tabB
assert.equal(readCurrentTrip(), 'shanxi-history')
globalThis.sessionStorage = storage() // a new tab can still find the last trip
assert.equal(readCurrentTrip(), 'hubei-running')
globalThis.sessionStorage = {getItem(){throw new Error('storage denied')},setItem(){throw new Error('storage denied')}}
assert.equal(readCurrentTrip(), 'hubei-running')
rememberCurrentTrip('wuhan-new')
assert.equal(readCurrentTrip(), 'wuhan-new')
console.log('PASS current trip: separate tabs survive refresh and polling; new-tab and denied-storage fallback')
