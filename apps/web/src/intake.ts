const KEY='ta-unsubmitted-idea-v1'
export function readIdea():string {try{return (localStorage.getItem(KEY)||'').slice(0,500)}catch{return ''}}
export function storeIdea(value:string):void {try{if(value)localStorage.setItem(KEY,value.slice(0,500));else localStorage.removeItem(KEY)}catch{/* input remains in memory */}}
export function submitShortcut(e:KeyboardEvent):boolean {return e.key==='Enter'&&(e.ctrlKey||e.metaKey)&&!e.isComposing&&e.keyCode!==229&&!e.repeat}
export function readMessage(session:string):string {try{return (localStorage.getItem('ta-unsubmitted-message-'+session)||'').slice(0,500)}catch{return ''}}
export function storeMessage(session:string,value:string):void {try{const key='ta-unsubmitted-message-'+session;if(value)localStorage.setItem(key,value.slice(0,500));else localStorage.removeItem(key)}catch{/* input remains in memory */}}
