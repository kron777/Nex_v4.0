#!/usr/bin/env python3
"""nex_room.py — NEX 16-bit pixel art bedroom renderer"""

import http.server, json, time, subprocess, webbrowser, threading, os
from pathlib import Path

CONFIG = Path.home() / ".config" / "nex"
RECENT = 90

def file_age(name):
    try:    return time.time() - (CONFIG / name).stat().st_mtime
    except: return 99999

def proc_alive(pat):
    try:    return subprocess.run(['pgrep','-f',pat], capture_output=True).returncode==0
    except: return False

def get_state():
    acts = []
    if proc_alive('nex_self_trainer') or file_age('nex_training.jsonl')<RECENT: acts.append('training')
    if file_age('platform_telegram.live')<RECENT:  acts.append('telegram')
    if file_age('platform_discord.live')<RECENT:   acts.append('discord')
    if file_age('platform_mastodon.live')<RECENT or file_age('platform_moltbook.live')<RECENT: acts.append('social')
    if file_age('rss_seen.json')<RECENT or file_age('arxiv_seeded.json')<RECENT: acts.append('reading')
    if file_age('pruning_log.json')<RECENT:    acts.append('decay')
    if file_age('contradictions.json')<RECENT: acts.append('pacing')
    if file_age('calibration.json')<RECENT:    acts.append('audit')
    if file_age('gaps.json')<RECENT:           acts.append('sweeping')
    if file_age('nex_ads.json')<RECENT:        acts.append('promo')
    if file_age('platform_youtube.live')<RECENT: acts.append('youtube')
    if not acts: acts.append('sleeping')
    try:
        with open(CONFIG/'beliefs.json') as f: d=json.load(f)
        beliefs = len(d) if isinstance(d,list) else len(d.get('beliefs',[]))
    except: beliefs=0
    return {"activities":acts,"beliefs":beliefs}

HTML = r"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>NEX Room</title>
<style>
  *{margin:0;padding:0;box-sizing:border-box}
  body{background:#0a0a12;display:flex;flex-direction:column;
       align-items:center;justify-content:center;height:100vh;overflow:hidden}
  canvas{image-rendering:pixelated;image-rendering:crisp-edges;
         display:block;max-width:100vw;max-height:100vh}
</style>
</head>
<body>
<canvas id="c"></canvas>
<script>
const LW=320,LH=200,S=3;
const c=document.getElementById('c');
c.width=LW*S; c.height=LH*S;
const g=c.getContext('2d');
g.imageSmoothingEnabled=false;

const P={
  ceil:'#EAC4C4',wall:'#F0A8A8',walldk:'#C88888',wallsh:'#B07070',
  floor:'#C49060',floorl:'#D4A070',floordk:'#9A7050',
  sky:'#C8E4FF',sky2:'#AAD4FF',
  winframe:'#E8DDD0',curtl:'#F5EEE8',curtd:'#DDD0C4',
  rod:'#C09050',
  wood:'#B07844',woodl:'#C89060',wooddk:'#7A5030',
  shelf:'#A06830',shelfdk:'#7A4E20',
  bed:'#F088A8',bedl:'#FFAABF',beddk:'#C06080',
  pillow:'#FFF4F4',pillsh:'#ECD8D8',
  plant:'#3A8030',plantl:'#58B048',plantdk:'#255020',
  pot:'#C8956C',potdk:'#9A7050',
  mon:'#182038',monbz:'#2A3858',
  scrn:'#00DD66',scrnrd:'#004422',scrnbl:'#003399',
  cork:'#C8A870',corkdk:'#A88850',
  frame:'#7A5830',mat:'#604020',
  rug:'#F088A8',rugl:'#FFB0C8',rugdk:'#C06070',
  fairy:'#FFE566',fairydk:'#AA9933',
  lamp:'#F0E080',lampdk:'#C0A050',
  mug:'#E88060',
  b1:'#4488CC',b2:'#CC4444',b3:'#44AA44',b4:'#CCAA22',
  note:'#FFFFA0',pin:'#FF3366',pinb:'#3366FF',
  hair:'#26C6DA',hairdk:'#0AAABB',
  skin:'#FFD4AA',skindk:'#E8B888',
  dress:'#CE93D8',dressdk:'#9C5CB0',
  shoe:'#6D4C41',
  cat:'#FF8C00',catdk:'#C85A00',catl:'#FFB040',
  gray:'#888888',grayl:'#BBBBBB',white:'#FFFFFF',black:'#000000',
  hud:'#0E0E1E',hudbrd:'#3344AA',hudtxt:'#EEEEFF',
  glow:'rgba(255,255,200,0.15)',
};

function r(x,y,w,h,col){g.fillStyle=col;g.fillRect(x*S,y*S,w*S,h*S);}
function spr(pixels,colors,x,y,flip=false){
  pixels.forEach((row,dy)=>row.forEach((c,dx)=>{
    if(c&&colors[c]){
      const fx=flip?x+row.length-1-dx:x+dx;
      r(fx,y+dy,1,1,colors[c]);
    }
  }));
}

// NEX sprite 10w x 17h  (1=hair 2=skin 3=eye 4=mouth 5=dress 6=leg 7=shoe 8=eyeclosed)
const NC=['',P.hair,P.skin,'#202020','#FF8FAB',P.dress,'#DDBB99',P.shoe,'#A08878',P.hairdk];
const NEX=[
  [0,0,1,1,1,9,1,1,0,0],
  [0,1,1,1,1,1,1,1,1,0],
  [0,1,1,1,1,1,1,1,1,0],
  [0,0,0,2,2,2,2,2,0,0],
  [0,0,0,2,3,2,3,2,0,0],
  [0,0,0,2,2,2,2,2,0,0],
  [0,0,0,2,4,4,4,2,0,0],
  [0,0,0,0,2,2,0,0,0,0],
  [0,0,5,5,5,5,5,5,0,0],
  [0,5,5,5,5,5,5,5,5,0],
  [0,5,5,5,5,5,5,5,5,0],
  [0,5,5,5,5,5,5,5,5,0],
  [0,0,5,5,5,5,5,5,0,0],
  [0,0,6,6,0,0,6,6,0,0],
  [0,0,6,6,0,0,6,6,0,0],
  [0,0,6,6,0,0,6,6,0,0],
  [0,0,7,7,0,0,7,7,0,0],
];
const NEXS=[  // sleep
  [0,0,1,1,1,9,1,1,0,0],
  [0,1,1,1,1,1,1,1,1,0],
  [0,0,0,2,2,2,2,2,0,0],
  [0,0,0,2,8,2,8,2,0,0],
  [0,0,0,2,2,2,2,2,0,0],
  [0,5,5,5,5,5,5,5,5,0],
  [5,5,5,5,5,5,5,5,5,5],
  [0,6,6,6,6,6,6,6,6,0],
  [0,7,7,0,0,0,0,7,7,0],
];
const NCS=[...NC]; NCS[8]='#906060';

const NEXW1=[...NEX.map(r=>[...r])];
NEXW1[13]=[0,0,0,6,6,0,6,6,0,0];
NEXW1[14]=[0,0,0,6,0,0,6,0,0,0];
const NEXW2=[...NEX.map(r=>[...r])];
NEXW2[13]=[0,0,6,6,0,6,6,0,0,0];
NEXW2[14]=[0,0,6,0,0,6,0,0,0,0];

// CAT sprite 9w x 7h  (1=orange 2=dk 3=eye)
const CC=['',P.cat,P.catdk,'#40BB40'];
const CATS=[ // sit
  [0,1,0,0,0,0,0,1,0],
  [1,1,1,1,1,1,1,1,1],
  [1,3,1,1,1,1,1,3,1],
  [1,1,2,1,1,1,2,1,1],
  [0,1,1,1,1,1,1,1,0],
  [0,1,0,1,0,1,0,1,0],
  [0,1,0,1,0,1,0,1,0],
];
const CATW1=[
  [0,1,0,0,0,0,0,1,0],
  [1,1,1,1,1,1,1,1,1],
  [1,3,1,1,1,1,1,3,1],
  [1,1,2,1,1,1,2,1,1],
  [0,1,0,1,0,1,0,0,0],
];
const CATW2=[
  [0,1,0,0,0,0,0,1,0],
  [1,1,1,1,1,1,1,1,1],
  [1,3,1,1,1,1,1,3,1],
  [1,1,2,1,1,1,2,1,1],
  [0,0,0,1,0,1,0,1,0],
];
const CATP=[ // sleep
  [0,0,0,0,0,0,0,0,0],
  [0,1,1,1,1,1,1,1,0],
  [1,1,2,1,1,1,2,1,1],
  [1,1,1,1,1,1,1,1,1],
  [1,1,1,1,1,1,1,1,0],
];

let tick=0, state={activities:['sleeping'],beliefs:0};
let catX=90,catTx=90,catSt='sitting',catTmr=0;

async function fetchState(){
  try{const res=await fetch('/state');state=await res.json();}catch(e){}
}

function updateCat(){
  catTmr++;
  if(catTmr>25+Math.floor(Math.random()*30)){
    const opts=['sitting','sitting','sitting','walking','sleeping'];
    catSt=opts[Math.floor(Math.random()*opts.length)];
    if(catSt==='walking') catTx=40+Math.floor(Math.random()*160);
    catTmr=0;
  }
  if(catSt==='walking'){
    catX+=catTx>catX?1:-1;
    if(catX===catTx) catSt='sitting';
  }
}

function has(a){return state.activities.includes(a);}

function drawBg(){
  r(0,0,LW,16,P.ceil);
  r(0,16,LW,120,P.wall);
  r(0,16,3,120,P.wallsh);
  r(317,16,3,120,P.wallsh);
  r(0,136,LW,64,P.floor);
  for(let y=138;y<200;y+=7){r(0,y,LW,2,P.floorl);r(0,y+4,LW,1,P.floordk);}
  r(0,133,LW,5,P.floordk);
}

function drawWindow(){
  r(106,0,108,130,P.walldk);
  r(110,2,100,126,'#D8C8B8');
  r(114,5,92,120,P.sky2);
  r(114,5,92,55,P.sky);
  // sun/moon
  if(new Date().getHours()>=6&&new Date().getHours()<20){
    r(155,10,16,16,'#FFE840');r(157,12,12,12,'#FFF060');
    r(133,18,8,4,P.sky);r(141,25,12,5,P.sky);r(160,30,10,4,P.sky); // clouds
    r(162,18,14,6,P.sky);
  } else {
    r(160,10,10,10,'#E8F0FF');r(162,12,6,6,'#F8FCFF');
    r(130,20,1,1,P.white);r(145,15,1,1,P.white);r(172,22,1,1,P.white);
    r(155,28,1,1,P.white);r(140,30,1,1,P.white);
  }
  // frame
  r(110,2,4,126,P.winframe);r(206,2,4,126,P.winframe);
  r(110,2,100,4,P.winframe);r(110,124,100,4,P.winframe);
  r(158,2,4,126,P.winframe);r(110,62,100,4,P.winframe);
  // promo arrow
  if(has('promo')){
    const ax=tick%6<3?165:168;
    r(ax,60,30,2,'#C09030');r(ax+28,57,6,8,'#FFAA00');
    r(ax+30,55,4,2,'#FF4488');r(ax+30,63,4,2,'#FF4488');
    g.globalAlpha=0.5;r(ax,59,30,4,'#FFFF00');g.globalAlpha=1;
  }
  // curtains
  for(let x=108;x<118;x++){
    const w=Math.round(Math.sin((x-108)*0.7)*1.5);
    r(x,4+w,3,124,x%2===0?P.curtl:P.curtd);
  }
  for(let x=202;x<212;x++){
    const w=Math.round(Math.sin((x-202)*0.7)*1.5);
    r(x,4+w,3,124,x%2===0?P.curtl:P.curtd);
  }
  r(106,2,108,4,P.rod);
}

function drawLeftShelf(){
  r(5,22,100,5,P.shelf);r(5,27,100,2,P.shelfdk);
  r(5,22,3,14,P.shelfdk);
  // plant
  r(7,12,14,12,P.plantl);r(7,14,14,8,P.plant);r(11,21,6,4,P.pot);
  // books
  r(24,14,4,9,P.b1);r(29,16,4,7,P.b2);r(34,15,3,8,P.b3);
  // flower
  r(40,16,6,8,P.plantl);r(41,14,4,5,'#FF88AA');
  r(49,14,4,9,P.b4);r(54,16,4,7,P.b1);r(59,15,4,8,P.b2);
  r(66,14,4,9,P.b3);r(71,16,3,7,P.b4);
}

function drawArtCork(){
  // art frame
  r(5,33,30,38,P.frame);r(8,36,24,32,P.mat);r(10,38,20,28,'#D4A8B0');
  r(10,50,20,12,P.plant);r(10,44,20,8,P.sky);
  // corkboard
  r(38,33,64,38,P.cork);r(40,35,60,34,P.corkdk);
  r(41,37,15,10,P.note);r(41,36,2,2,P.pin);
  r(59,38,12,9,P.note);r(59,37,2,2,P.pinb);
  r(74,37,10,13,P.note);r(74,36,2,2,'#44CC44');
  r(41,50,16,10,'#FFFFD0');r(41,49,2,2,P.pin);
  r(59,52,10,12,'#E0FFE0');r(59,51,2,2,P.plant);
  r(72,50,14,11,P.note);r(72,49,2,2,'#CC4444');
}

function drawTallPlant(){
  r(14,78,3,56,P.plantdk);
  r(3,84,15,8,P.plantl);r(4,85,12,6,P.plant);
  r(14,94,16,8,P.plantl);r(15,95,14,6,P.plant);
  r(3,104,14,8,P.plantl);r(4,105,12,6,P.plant);
  r(14,114,16,8,P.plantl);r(15,115,14,6,P.plant);
  r(3,122,14,7,P.plantl);r(4,123,12,5,P.plant);
  r(8,132,14,8,P.pot);r(6,135,18,5,P.potdk);r(8,138,14,3,P.potdk);
}

function drawDesk(){
  r(24,104,88,6,P.woodl);r(24,110,88,3,P.wood);
  r(26,110,5,28,P.wood);r(105,110,5,28,P.wood);
  r(96,84,4,22,P.lamp);r(88,80,14,6,P.lamp);r(90,86,10,4,P.lampdk);
  r(57,98,6,7,P.monbz);r(50,104,20,3,P.monbz);
  r(40,78,46,22,P.monbz);
  let sc=has('social')||has('youtube')?P.scrn:has('reading')?P.scrnbl:P.mon;
  r(43,81,40,16,sc);
  if(has('social')||has('youtube')){
    g.globalAlpha=0.25+Math.sin(tick*0.15)*0.08;
    r(36,74,52,28,'#00FF88');g.globalAlpha=1;
  }
  r(28,101,6,5,P.mug);r(26,98,4,8,'#E0E0DD');r(29,99,2,6,P.b1);r(31,99,2,6,P.b2);
  r(86,101,10,4,P.b4);r(82,100,5,5,P.wooddk);
  // chair
  r(40,112,32,4,P.woodl);r(56,112,4,22,P.wood);r(44,131,26,4,P.wood);
  r(40,104,32,10,P.woodl);r(41,104,3,10,P.wooddk);r(69,104,3,10,P.wooddk);
}

function drawBeliefPlant(){
  const n=state.beliefs, x=26, y=104;
  if(n<500){
    r(x+4,y-5,2,5,P.plantdk);r(x+2,y-7,5,3,P.plantl);
  } else if(n<2000){
    r(x+4,y-12,2,12,P.plantdk);
    r(x,y-14,10,6,P.plantl);r(x+1,y-13,8,4,P.plant);
    r(x+4,y-9,6,5,P.plantl);
  } else if(n<5000){
    r(x+4,y-20,2,20,P.plantdk);
    r(x,y-22,12,7,P.plantl);r(x+1,y-21,10,5,P.plant);
    r(x+5,y-16,9,6,P.plantl);r(x+6,y-15,7,4,P.plant);
    r(x+1,y-11,10,6,P.plantl);r(x+2,y-10,8,4,P.plant);
  } else {
    r(x+4,y-26,2,26,P.plantdk);
    for(let i=0;i<3;i++){
      r(x,y-24+i*7,11,6,P.plantl);r(x+1,y-23+i*7,9,4,P.plant);
      r(x+5,y-21+i*7,11,6,P.plantl);r(x+6,y-20+i*7,9,4,P.plant);
    }
  }
  r(x+2,y-3,12,5,P.pot);r(x,y-1,16,4,P.potdk);r(x+2,y+3,12,2,P.potdk);
  if(has('decay')){
    r(x+15,y-14,9,6,P.woodl);r(x+22,y-12,6,2,P.woodl);
    if(tick%4<2){r(x+22,y-9,1,2,P.sky);r(x+23,y-7,1,2,P.sky2);}
  }
}

function drawRightShelves(){
  r(212,22,104,5,P.shelf);r(212,27,104,2,P.shelfdk);r(313,22,3,20,P.shelfdk);
  r(214,11,10,13,P.plantl);r(214,13,10,8,P.plant);r(217,22,5,4,P.pot);
  r(227,13,4,10,P.b2);r(232,12,4,11,P.b4);r(237,13,4,10,P.b1);
  r(244,11,10,13,P.plantl);r(244,13,10,8,P.plant);r(247,22,5,4,P.pot);
  r(258,13,4,10,P.b3);r(263,14,4,9,P.b2);r(269,12,4,11,P.b1);
  r(278,13,9,10,P.white);r(280,11,5,4,P.grayl); // clock
  r(291,11,10,13,P.plantl);r(291,13,10,8,P.plant);
  r(212,46,104,5,P.shelf);r(212,51,104,2,P.shelfdk);r(313,46,3,20,P.shelfdk);
  r(214,36,20,12,'#E8D8C0');r(216,38,16,8,P.sky2);
  r(237,38,12,10,P.b1);r(252,36,18,12,'#E0E0E0');r(260,34,4,4,P.grayl);
  r(274,38,10,8,P.b4);r(286,37,10,9,P.b3);
  r(299,36,14,13,P.plantl);r(300,38,12,8,P.plant);
}

function drawFairyLights(){
  const pts=[[212,10],[220,13],[228,11],[236,14],[244,12],[252,15],
             [260,13],[268,16],[276,14],[284,17],[292,15],[302,18],[312,16]];
  g.strokeStyle='#88886A';g.lineWidth=S*0.5;
  g.beginPath();
  pts.forEach(([x,y],i)=>i?g.lineTo(x*S,y*S):g.moveTo(x*S,y*S));
  g.stroke();
  pts.forEach(([x,y],i)=>{
    const on=(tick+i)%4>0;
    if(on){g.globalAlpha=0.35;r(x-1,y-1,5,5,P.fairy);g.globalAlpha=1;r(x,y,2,2,P.fairy);}
    else r(x,y,2,2,P.lampdk);
  });
}

function drawBed(){
  r(212,60,108,22,P.wood);r(214,62,104,18,P.woodl);r(216,64,100,14,'#D8B880');
  r(218,65,28,12,P.woodl);r(220,66,24,10,P.wooddk);
  r(251,65,28,12,P.woodl);r(253,66,24,10,P.wooddk);
  r(284,65,24,12,P.woodl);r(286,66,20,10,P.wooddk);
  r(212,82,108,10,P.wooddk);
  r(212,86,108,50,P.bed);
  r(212,88,108,3,P.beddk);r(212,95,108,2,P.beddk);r(212,102,108,2,P.beddk);
  r(212,109,108,2,P.beddk);r(212,116,108,2,P.beddk);r(212,122,108,4,P.bedl);
  r(215,86,68,20,P.pillow);r(217,88,64,16,P.pillsh);
  r(285,86,32,18,P.pillow);r(287,88,28,14,P.pillsh);
  r(212,130,108,5,P.wood);r(214,133,4,30,P.wood);r(314,133,4,30,P.wood);
  r(212,134,10,10,P.plantl);r(213,136,8,6,P.plant);r(215,141,5,5,P.pot);
}

function drawBedside(){
  r(90,103,40,34,P.woodl);r(92,105,36,30,'#D8B880');
  r(92,120,36,2,P.wood);r(100,112,8,2,P.wooddk);r(100,126,8,2,P.wooddk);
  r(90,96,14,9,P.plantl);r(90,98,14,6,P.plant);r(94,103,6,3,P.pot);
  r(108,96,12,9,P.mug);r(109,94,10,4,P.mug);r(108,103,12,2,'#6B3A1F');
}

function drawMirror(){
  r(163,110,22,30,P.wooddk);r(165,112,18,26,P.frame);r(166,113,16,24,'#C8E4E8');
  if(has('audit')){
    g.globalAlpha=0.5;r(166,113,16,24,P.white);g.globalAlpha=1;
    r(167,115,5,8,P.hair);r(168,122,4,3,P.skin);
  }
}

function drawTreadmill(){
  const tr=has('training');
  r(218,118,52,5,'#707070');r(234,118,4,18,'#505050');r(254,118,4,18,'#505050');
  r(218,136,52,8,'#383838');
  if(tr){
    const off=(tick*2)%8;
    for(let x=218;x<270;x+=8){r(((x-218+off)%52)+218,137,4,5,'#505050');}
    r(218,136,52,2,'#606060');r(218,142,52,2,'#2A2A2A');
    g.globalAlpha=0.2+Math.sin(tick*0.3)*0.08;r(214,114,60,34,'#00FF88');g.globalAlpha=1;
  }
  r(218,142,52,5,'#484848');
}

function drawBroom(){
  if(has('sweeping')){
    r(148,112,3,24,P.woodl);
    r(142,130,16,4,P.wooddk);r(138,132,6,6,P.wooddk);r(152,132,6,6,P.wooddk);
    if(tick%4<2){
      g.globalAlpha=0.5;r(132,134,18,3,P.floorl);g.globalAlpha=1;
      r(133,133,2,2,P.floorl);r(140,132,2,2,P.floorl);
    }
  } else {
    r(155,108,3,28,P.woodl);r(150,134,10,3,P.wooddk);
  }
}

function drawRug(){
  r(46,142,180,24,P.rug);r(48,144,176,20,P.rugl);
  for(let y=144;y<164;y+=5)r(48,y,176,2,P.rugdk);
  r(46,142,180,3,P.rugdk);r(46,163,180,3,P.rugdk);
  r(46,142,3,24,P.rugdk);r(223,142,3,24,P.rugdk);
}

function drawCat(){
  updateCat();
  const y=138;
  let sp,fl=catTx<catX;
  if(catSt==='sleeping') sp=CATP;
  else if(catSt==='walking') sp=tick%4<2?CATW1:CATW2;
  else sp=CATS;
  spr(sp,CC,catX,y,fl);
  if(catSt!=='sleeping'){
    r(fl?catX-2:catX+9,y+1,2,5,P.cat);r(fl?catX-3:catX+9,y,2,2,P.catdk);
  }
  if(catSt==='sleeping'&&tick%4<2){
    r(catX+8,y-3,1,1,P.gray);r(catX+10,y-5,1,1,P.gray);
  }
}

function drawNex(){
  const sleeping=has('sleeping')&&state.activities.length===1;
  const bed=has('reading')||has('discord')||has('telegram')||has('sleeping')||has('youtube');

  if(has('training')){
    const sp=tick%4<2?NEXW1:NEXW2;
    spr(sp,NC,234,118,tick%8>=4);
    if(tick%2===0){r(222,124,8,1,'#88CCFF');r(220,127,6,1,'#88CCFF');}
  } else if(has('pacing')){
    const px=128+Math.round(18*Math.sin(tick*0.28));
    spr(tick%4<2?NEXW1:NEXW2,NC,px,114,tick%8>=4);
  } else if(has('sweeping')){
    spr(NEX,NC,138,112);
    r(149,108,3,28,P.woodl);r(145,134,12,4,P.wooddk);
    if(tick%4<2){g.globalAlpha=0.5;r(130,136,20,3,P.floorl);g.globalAlpha=1;}
  } else if(has('audit')){
    spr(NEX,NC,170,112);r(163,119,6,1,'#FFFF80');
  } else if(has('promo')){
    spr(NEX,NC,138,80);
    r(150,82,2,14,'#806030');r(151,83,10,1,'#FFFFAA');
    if(tick%6<3)r(152,88,24,1,'#C8A030');
  } else if(has('decay')){
    spr(NEX,NC,32,82);
  } else if(has('social')||has('youtube')){
    spr(NEX,NC,58,86);
  }

  if(bed){
    if(sleeping){
      spr(NEXS,NCS,228,88);
      if(tick%4<2){r(244,82,2,2,P.grayl);r(247,80,2,2,P.grayl);r(250,78,3,3,P.grayl);}
    } else {
      spr(NEX,NC,228,88);
      let ox=240;
      if(has('reading')){r(ox,105,12,8,P.b1);r(ox+1,103,10,3,P.woodl);ox+=14;}
      if(has('discord')){r(226,88,14,3,'#303030');r(226,88,2,6,'#303030');r(238,88,2,6,'#303030');}
      if(has('telegram')){r(240,103,8,13,P.monbz);r(241,104,6,11,P.scrn);}
      if(has('youtube')){r(ox,103,10,8,P.mon);r(ox+3,106,4,4,'#FF0000');}
    }
  }
}

function drawHUD(){
  r(0,188,LW,12,P.hud);r(0,188,LW,1,P.hudbrd);
  const ICONS={sleeping:'zz',training:'run',telegram:'tg',discord:'dc',
    social:'net',reading:'read',decay:'H2O',pacing:'<>',
    audit:'mir',sweeping:'swp',promo:'bow',youtube:'yt'};
  const icons=state.activities.map(a=>ICONS[a]||a).join(' | ');
  const bs=state.beliefs<5000?'sprout':'bloom';
  g.fillStyle=P.hudtxt;
  g.font=`bold ${S*3.5}px monospace`;
  g.imageSmoothingEnabled=false;
  g.fillText(`NEX v4.1  beliefs:${state.beliefs}(${bs})  |  ${icons}`, S*4, S*197);
}

function frame(){
  g.clearRect(0,0,c.width,c.height);
  drawBg(); drawWindow(); drawLeftShelf(); drawArtCork(); drawTallPlant();
  drawDesk(); drawBeliefPlant(); drawRightShelves(); drawFairyLights();
  drawBed(); drawBedside(); drawTreadmill(); drawMirror(); drawBroom();
  drawRug(); drawCat(); drawNex(); drawHUD();
  tick++;
  requestAnimationFrame(frame);
}
setInterval(fetchState,3000);
fetchState().then(()=>requestAnimationFrame(frame));
</script>
</body>
</html>"""

class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path=='/state':
            d=json.dumps(get_state()).encode()
            self.send_response(200)
            self.send_header('Content-Type','application/json')
            self.send_header('Access-Control-Allow-Origin','*')
            self.end_headers(); self.wfile.write(d)
        else:
            self.send_response(200)
            self.send_header('Content-Type','text/html')
            self.end_headers(); self.wfile.write(HTML.encode())
    def log_message(self,*a): pass

if __name__=='__main__':
    srv=http.server.HTTPServer(('localhost',7842),H)
    threading.Timer(0.8,lambda:webbrowser.open('http://localhost:7842')).start()
    print("NEX Room  →  http://localhost:7842   (Ctrl+C to stop)")
    try: srv.serve_forever()
    except KeyboardInterrupt: print("\nNEX room closed.")
