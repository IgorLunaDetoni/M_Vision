/* Original vector miniatures. Bows point north; the map applies AIS heading. */
"use strict";
window.MVisionIcons = (() => {
  const rect=(x,y,w,h,fill,rx=1)=>`<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="${rx}" fill="${fill}"/>`;
  const line=(x1,y1,x2,y2,stroke="#d1e4ec",width=1)=>`<path d="M${x1} ${y1}L${x2} ${y2}" fill="none" stroke="${stroke}" stroke-width="${width}" stroke-linecap="round"/>`;
  const circle=(x,y,r,fill,stroke="#e6f2f6")=>`<circle cx="${x}" cy="${y}" r="${r}" fill="${fill}" stroke="${stroke}" stroke-width="1"/>`;
  const bridge=(y=84)=>rect(14,y,36,13,"#edf3ef",3)+rect(17,y+2,30,4,"#315a70",1)+rect(23,y+8,18,7,"#fafbf7",1)+rect(27,y+14,10,5,"#d77651",1);
  const hull=(deck,wide=false)=>`<path d="M32 3C${wide?12:17} 12 8 25 8 43v57q24 11 48 0V43C56 25 ${wide?52:47} 12 32 3Z" fill="currentColor" stroke="#e4edf2" stroke-width="1.6"/><path d="M32 11C20 21 13 31 13 45v51q19 7 38 0V45c0-14-7-24-19-34Z" fill="${deck}"/><path d="M32 8v10M13 48v42M51 48v42" stroke="#e6f5f4" stroke-opacity=".45" fill="none"/>`;
  const industrial=(deck,content)=>hull(deck)+content+bridge();
  const container=industrial("#304b57",
    [23,38,53,68].map((y,row)=>[16,27,38].map((x,col)=>rect(x,y,10,13,["#e7a54b","#518fa7","#cb6c52","#8eaf80"][(row+col)%4],.5)+line(x+3,y+2,x+3,y+11,"#ffffff45",.7)+line(x+7,y+2,x+7,y+11,"#00000035",.7)).join('')).join(''));
  const tanker=industrial("#a15742",
    rect(18,24,28,55,"#773d32",3)+[31,48,65].map(y=>circle(32,y,7,"#c98a67")+circle(32,y,2,"#78462f")).join('')+
    line(19,22,19,80,"#f6dba7",2)+line(45,22,45,80,"#f6dba7",2)+[31,48,65].map(y=>line(19,y,45,y,"#e3b583",1.5)).join(''));
  const bulk=industrial("#71634d",
    [23,43,63].map(y=>rect(16,y,32,17,"#423b35",1)+rect(18,y+2,28,13,"#c0a578",1)+line(19,y+8,45,y+8,"#8f734c",1)+line(32,y+3,32,y+13,"#e7d3aa",.8)).join(''));
  const gas=industrial("#4c6b6d",
    [32,52,72].map(y=>circle(32,y,12,"#e5e7d6")+`<path d="M22 ${y}q10-12 20 0M32 ${y-11}v22" fill="none" stroke="#a5bbb5" stroke-width="1.2"/>`+circle(29,y-3,3,"#fffdf0","#fffdf0")).join(''));
  const cargo=industrial("#547568",
    [27,55].map(y=>rect(17,y,30,22,"#2c4b47",1)+rect(19,y+2,26,18,"#96b4a1",1)).join('')+
    [23,52].map(y=>circle(45,y,2,"#eacb79")+line(45,y,19,y+13,"#f6d890",2.5)+line(45,y+3,24,y+15,"#2f4946",.8)).join(''));
  const fishing=hull("#3e706b",true)+bridge(26)+rect(16,50,32,43,"#234a4f",2)+
    [63,79].map(y=>circle(26,y,6,"#718f8b")+circle(39,y,5,"#c8a572")).join('')+
    line(13,89,13,50,"#ded5b6",2)+line(51,89,51,50,"#ded5b6",2)+line(13,50,51,50,"#ded5b6",2)+
    `<path d="M19 91q13-17 26 0M20 91l4-13 7 9 9-9 4 13" fill="none" stroke="#bed0b7" stroke-width="1"/>`;
  const tug=`<path d="M32 9C15 12 6 28 6 45v44q0 16 26 18t26-18V45C58 28 49 12 32 9Z" fill="#172633" stroke="currentColor" stroke-width="4"/><path d="M32 17C18 22 13 33 13 46v43q19 16 38 0V46c0-13-5-24-19-29Z" fill="currentColor"/>`+
    rect(17,31,30,35,"#f2ebd8",5)+rect(20,34,24,8,"#254a60",2)+rect(23,45,18,17,"#fff7e5",2)+rect(28,63,8,9,"#b9543b",1)+
    circle(32,85,9,"#243d49")+circle(32,85,3,"#e6ddbc")+[35,55,75].map(y=>line(7,y,13,y,"#0c1722",5)+line(51,y,57,y,"#0c1722",5)).join('');
  const passenger=hull("#c4d3d4")+`<path d="M32 19Q18 28 17 45v47q15 8 30 0V45Q46 28 32 19Z" fill="#f1f4eb"/>`+
    [35,48,61,74,87].map(y=>rect(17,y,5,7,"#427790")+rect(42,y,5,7,"#427790")).join('')+
    rect(25,39,14,42,"#dce8e5",4)+rect(27,48,10,21,"#4eb4c0",4)+rect(27,76,10,9,"#d59752",1)+line(23,30,41,30,"#355f75",3);
  const sailing=`<path d="M32 4C20 20 20 44 21 64l4 36q7 12 14 0l4-36c1-20 1-44-11-60Z" fill="#f1f2e3" stroke="currentColor" stroke-width="2"/>`+
    rect(26,62,12,25,"#4c7f94",4)+line(32,17,32,100,"#d7b58b",2)+
    `<path d="M30 22L7 78l23-9Z" fill="#e7f5ef" stroke="#779db0" stroke-width="1"/><path d="M35 33l22 48-22-8Z" fill="currentColor" stroke="#daf1f3" stroke-width="1"/><path d="M26 40L13 73M39 48l13 28" stroke="#a2bbc5" stroke-width=".7" fill="none"/>`;
  const pleasure=`<path d="M32 4C18 17 13 39 14 65l4 32q14 15 28 0l4-32c1-26-4-48-18-61Z" fill="#f4f0e4" stroke="currentColor" stroke-width="2"/>`+
    `<path d="M32 18q-13 14-13 40h26q0-26-13-40Z" fill="#c8dedf"/><path d="M23 46q9-10 18 0l2 23H21Z" fill="#396b86"/>`+
    rect(24,52,16,24,"#eaf1e9",5)+rect(22,78,20,15,"#a58b69",3)+rect(26,80,12,8,"#e5ddd0",2)+line(23,96,41,96,"#7ba7b7",1);
  const other=industrial("#586a73",rect(18,25,28,19,"#c4d0cd",2)+rect(18,52,28,24,"#324754",2)+line(45,49,19,69,"#e2be79",3)+circle(45,49,3,"#cdb27b"));
  const unknown=hull("#485d6b")+rect(21,35,22,37,"#c7d7dc",4)+rect(24,39,16,10,"#345a6e",2)+line(22,79,42,79,"#a0b7c2",2);
  const aircraft=`<path d="M29 9q3-7 6 0l3 34 23 26v8L38 64l-1 25 10 13v4l-15-7-15 7v-4l10-13-1-25L3 77v-8l23-26Z" fill="currentColor" stroke="#dbeeff" stroke-width="1.6"/><path d="M29 22h6l1 12h-8Z" fill="#294f68"/>`;
  const artwork=Object.freeze({container,tanker,bulk,gas,cargo,fishing,tug,passenger,sailing,pleasure,other,unknown,aircraft});
  return Object.freeze({
    types:Object.freeze(Object.keys(artwork)),
    svg(type){
      const name=Object.hasOwn(artwork,type)?type:'unknown';
      return `<svg viewBox="0 0 64 112" xmlns="http://www.w3.org/2000/svg" aria-hidden="true" focusable="false" class="vessel-art vessel-art-${name}">${artwork[name]}</svg>`;
    }
  });
})();
