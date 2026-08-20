"""Small mobile depth refinement layered after the main Meeting presentation patch."""

REFINE_CSS = r'''
<style id="m4-mobile-depth-refine">
/* Preserve the generated room as a room, not a smeared backdrop. */
.room{background-position:50% 42%!important}
.room:before{background:radial-gradient(ellipse at 50% 45%,rgba(255,192,118,.035) 0 17%,transparent 42%,rgba(0,0,0,.12) 72%,rgba(0,0,0,.34) 100%)!important}
.room:after{background:linear-gradient(180deg,rgba(0,0,0,.05),transparent 22% 72%,rgba(0,0,0,.18))!important}

/* Make M4 occupy space in the room instead of reading as a decal. */
.presence{transform:translateY(-3.8vh) scale(.90)!important;filter:drop-shadow(0 34px 18px rgba(0,0,0,.62)) drop-shadow(0 0 18px rgba(255,202,133,.10))!important}
.presence:before{opacity:.88!important;filter:brightness(.83) saturate(.62) contrast(1.08)!important}
.presence:after{left:20%!important;right:20%!important;bottom:-13%!important;height:10%!important;background:radial-gradient(ellipse,rgba(0,0,0,.60),rgba(0,0,0,0) 70%)!important;filter:blur(8px)!important;opacity:.74!important}
.presence.listening{transform:translateY(-4.2vh) scale(.94)!important}
.presence.thinking{transform:translateY(-3.2vh) scale(.87)!important}
.presence.speaking{transform:translateY(-4.1vh) scale(.93)!important}

/* Quiet UI even further on phones. */
.status{bottom:max(16px,calc(env(safe-area-inset-bottom) + 8px))!important;max-width:62vw!important;padding:5px 9px 6px!important;background:rgba(5,5,4,.20)!important;border-color:rgba(255,255,255,.07)!important}
.state{font-size:7px!important}.hint{font-size:9px!important}
.controls{top:max(10px,env(safe-area-inset-top))!important;right:10px!important}.control{width:36px!important;height:36px!important;background:rgba(5,5,4,.18)!important}

@media(min-width:760px){
 .room{background-position:center center!important}
 .presence{transform:translateY(-2vh) scale(.92)!important}
 .presence.listening{transform:translateY(-2.4vh) scale(.96)!important}
 .presence.thinking{transform:translateY(-1.4vh) scale(.89)!important}
 .presence.speaking{transform:translateY(-2.3vh) scale(.95)!important}
}
</style>
'''


def enhance(html: str) -> str:
    if 'id="m4-mobile-depth-refine"' in html:
        return html
    return html.replace("</head>", REFINE_CSS + "</head>")
