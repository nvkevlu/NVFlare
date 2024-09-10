(self.webpackChunk_N_E=self.webpackChunk_N_E||[]).push([[874],{27484:function(e){e.exports=function(){"use strict";var e=1e3,t=6e4,n=36e5,r="millisecond",i="second",s="minute",o="hour",u="day",a="week",c="month",l="quarter",f="year",h="date",d="Invalid Date",p=/^(\d{4})[-/]?(\d{1,2})?[-/]?(\d{0,2})[Tt\s]*(\d{1,2})?:?(\d{1,2})?:?(\d{1,2})?[.:]?(\d+)?$/,m=/\[([^\]]+)]|Y{1,4}|M{1,4}|D{1,2}|d{1,4}|H{1,2}|h{1,2}|a|A|m{1,2}|s{1,2}|Z{1,2}|SSS/g,g={name:"en",weekdays:"Sunday_Monday_Tuesday_Wednesday_Thursday_Friday_Saturday".split("_"),months:"January_February_March_April_May_June_July_August_September_October_November_December".split("_"),ordinal:function(e){var t=["th","st","nd","rd"],n=e%100;return"["+e+(t[(n-20)%10]||t[n]||t[0])+"]"}},v=function(e,t,n){var r=String(e);return!r||r.length>=t?e:""+Array(t+1-r.length).join(n)+e},$={s:v,z:function(e){var t=-e.utcOffset(),n=Math.abs(t),r=Math.floor(n/60),i=n%60;return(t<=0?"+":"-")+v(r,2,"0")+":"+v(i,2,"0")},m:function e(t,n){if(t.date()<n.date())return-e(n,t);var r=12*(n.year()-t.year())+(n.month()-t.month()),i=t.clone().add(r,c),s=n-i<0,o=t.clone().add(r+(s?-1:1),c);return+(-(r+(n-i)/(s?i-o:o-i))||0)},a:function(e){return e<0?Math.ceil(e)||0:Math.floor(e)},p:function(e){return{M:c,y:f,w:a,d:u,D:h,h:o,m:s,s:i,ms:r,Q:l}[e]||String(e||"").toLowerCase().replace(/s$/,"")},u:function(e){return void 0===e}},M="en",y={};y[M]=g;var x="$isDayjsObject",S=function(e){return e instanceof b||!(!e||!e[x])},w=function e(t,n,r){var i;if(!t)return M;if("string"==typeof t){var s=t.toLowerCase();y[s]&&(i=s),n&&(y[s]=n,i=s);var o=t.split("-");if(!i&&o.length>1)return e(o[0])}else{var u=t.name;y[u]=t,i=u}return!r&&i&&(M=i),i||!r&&M},j=function(e,t){if(S(e))return e.clone();var n="object"==typeof t?t:{};return n.date=e,n.args=arguments,new b(n)},D=$;D.l=w,D.i=S,D.w=function(e,t){return j(e,{locale:t.$L,utc:t.$u,x:t.$x,$offset:t.$offset})};var b=function(){function g(e){this.$L=w(e.locale,null,!0),this.parse(e),this.$x=this.$x||e.x||{},this[x]=!0}var v=g.prototype;return v.parse=function(e){this.$d=function(e){var t=e.date,n=e.utc;if(null===t)return new Date(NaN);if(D.u(t))return new Date;if(t instanceof Date)return new Date(t);if("string"==typeof t&&!/Z$/i.test(t)){var r=t.match(p);if(r){var i=r[2]-1||0,s=(r[7]||"0").substring(0,3);return n?new Date(Date.UTC(r[1],i,r[3]||1,r[4]||0,r[5]||0,r[6]||0,s)):new Date(r[1],i,r[3]||1,r[4]||0,r[5]||0,r[6]||0,s)}}return new Date(t)}(e),this.init()},v.init=function(){var e=this.$d;this.$y=e.getFullYear(),this.$M=e.getMonth(),this.$D=e.getDate(),this.$W=e.getDay(),this.$H=e.getHours(),this.$m=e.getMinutes(),this.$s=e.getSeconds(),this.$ms=e.getMilliseconds()},v.$utils=function(){return D},v.isValid=function(){return!(this.$d.toString()===d)},v.isSame=function(e,t){var n=j(e);return this.startOf(t)<=n&&n<=this.endOf(t)},v.isAfter=function(e,t){return j(e)<this.startOf(t)},v.isBefore=function(e,t){return this.endOf(t)<j(e)},v.$g=function(e,t,n){return D.u(e)?this[t]:this.set(n,e)},v.unix=function(){return Math.floor(this.valueOf()/1e3)},v.valueOf=function(){return this.$d.getTime()},v.startOf=function(e,t){var n=this,r=!!D.u(t)||t,l=D.p(e),d=function(e,t){var i=D.w(n.$u?Date.UTC(n.$y,t,e):new Date(n.$y,t,e),n);return r?i:i.endOf(u)},p=function(e,t){return D.w(n.toDate()[e].apply(n.toDate("s"),(r?[0,0,0,0]:[23,59,59,999]).slice(t)),n)},m=this.$W,g=this.$M,v=this.$D,$="set"+(this.$u?"UTC":"");switch(l){case f:return r?d(1,0):d(31,11);case c:return r?d(1,g):d(0,g+1);case a:var M=this.$locale().weekStart||0,y=(m<M?m+7:m)-M;return d(r?v-y:v+(6-y),g);case u:case h:return p($+"Hours",0);case o:return p($+"Minutes",1);case s:return p($+"Seconds",2);case i:return p($+"Milliseconds",3);default:return this.clone()}},v.endOf=function(e){return this.startOf(e,!1)},v.$set=function(e,t){var n,a=D.p(e),l="set"+(this.$u?"UTC":""),d=(n={},n[u]=l+"Date",n[h]=l+"Date",n[c]=l+"Month",n[f]=l+"FullYear",n[o]=l+"Hours",n[s]=l+"Minutes",n[i]=l+"Seconds",n[r]=l+"Milliseconds",n)[a],p=a===u?this.$D+(t-this.$W):t;if(a===c||a===f){var m=this.clone().set(h,1);m.$d[d](p),m.init(),this.$d=m.set(h,Math.min(this.$D,m.daysInMonth())).$d}else d&&this.$d[d](p);return this.init(),this},v.set=function(e,t){return this.clone().$set(e,t)},v.get=function(e){return this[D.p(e)]()},v.add=function(r,l){var h,d=this;r=Number(r);var p=D.p(l),m=function(e){var t=j(d);return D.w(t.date(t.date()+Math.round(e*r)),d)};if(p===c)return this.set(c,this.$M+r);if(p===f)return this.set(f,this.$y+r);if(p===u)return m(1);if(p===a)return m(7);var g=(h={},h[s]=t,h[o]=n,h[i]=e,h)[p]||1,v=this.$d.getTime()+r*g;return D.w(v,this)},v.subtract=function(e,t){return this.add(-1*e,t)},v.format=function(e){var t=this,n=this.$locale();if(!this.isValid())return n.invalidDate||d;var r=e||"YYYY-MM-DDTHH:mm:ssZ",i=D.z(this),s=this.$H,o=this.$m,u=this.$M,a=n.weekdays,c=n.months,l=n.meridiem,f=function(e,n,i,s){return e&&(e[n]||e(t,r))||i[n].slice(0,s)},h=function(e){return D.s(s%12||12,e,"0")},p=l||function(e,t,n){var r=e<12?"AM":"PM";return n?r.toLowerCase():r};return r.replace(m,(function(e,r){return r||function(e){switch(e){case"YY":return String(t.$y).slice(-2);case"YYYY":return D.s(t.$y,4,"0");case"M":return u+1;case"MM":return D.s(u+1,2,"0");case"MMM":return f(n.monthsShort,u,c,3);case"MMMM":return f(c,u);case"D":return t.$D;case"DD":return D.s(t.$D,2,"0");case"d":return String(t.$W);case"dd":return f(n.weekdaysMin,t.$W,a,2);case"ddd":return f(n.weekdaysShort,t.$W,a,3);case"dddd":return a[t.$W];case"H":return String(s);case"HH":return D.s(s,2,"0");case"h":return h(1);case"hh":return h(2);case"a":return p(s,o,!0);case"A":return p(s,o,!1);case"m":return String(o);case"mm":return D.s(o,2,"0");case"s":return String(t.$s);case"ss":return D.s(t.$s,2,"0");case"SSS":return D.s(t.$ms,3,"0");case"Z":return i}return null}(e)||i.replace(":","")}))},v.utcOffset=function(){return 15*-Math.round(this.$d.getTimezoneOffset()/15)},v.diff=function(r,h,d){var p,m=this,g=D.p(h),v=j(r),$=(v.utcOffset()-this.utcOffset())*t,M=this-v,y=function(){return D.m(m,v)};switch(g){case f:p=y()/12;break;case c:p=y();break;case l:p=y()/3;break;case a:p=(M-$)/6048e5;break;case u:p=(M-$)/864e5;break;case o:p=M/n;break;case s:p=M/t;break;case i:p=M/e;break;default:p=M}return d?p:D.a(p)},v.daysInMonth=function(){return this.endOf(c).$D},v.$locale=function(){return y[this.$L]},v.locale=function(e,t){if(!e)return this.$L;var n=this.clone(),r=w(e,t,!0);return r&&(n.$L=r),n},v.clone=function(){return D.w(this.$d,this)},v.toDate=function(){return new Date(this.valueOf())},v.toJSON=function(){return this.isValid()?this.toISOString():null},v.toISOString=function(){return this.$d.toISOString()},v.toString=function(){return this.$d.toUTCString()},g}(),C=b.prototype;return j.prototype=C,[["$ms",r],["$s",i],["$m",s],["$H",o],["$W",u],["$M",c],["$y",f],["$D",h]].forEach((function(e){C[e[1]]=function(t){return this.$g(t,e[0],e[1])}})),j.extend=function(e,t){return e.$i||(e(t,b,j),e.$i=!0),j},j.locale=w,j.isDayjs=S,j.unix=function(e){return j(1e3*e)},j.en=y[M],j.Ls=y,j.p={},j}()},89924:function(e,t,n){"use strict";n.d(t,{y:function(){return v}});var r=n(9669),i=n.n(r),s=n(84506),o=n(68253),u=n(35823),a=n.n(u),c=s,l=i().create({baseURL:c.url_root+"/api/v1/",headers:{"Access-Control-Allow-Origin":"*"}});l.interceptors.request.use((function(e){return e.headers.Authorization="Bearer "+(0,o.Gg)().user.token,e}),(function(e){console.log("Interceptor request error: "+e)})),l.interceptors.response.use((function(e){return e}),(function(e){throw console.log(" AXIOS error: "),console.log(e),401===e.response.status&&(0,o.KY)("","",-1,0,"",!0),403===e.response.status&&console.log("Error: "+e.response.data.status),404===e.response.status&&console.log("Error: "+e.response.data.status),409===e.response.status&&console.log("Error: "+e.response.data.status),422===e.response.status&&(0,o.KY)("","",-1,0,"",!0),e}));var f=function(e){return e.data},h=function(e){return l.get(e).then(f)},d=function(e,t,n){return l.post(e,{pin:n},{responseType:"blob"}).then((function(e){t=e.headers["content-disposition"].split('"')[1],a()(e.data,t)}))},p=function(e,t){return l.post(e,t).then(f)},m=function(e,t){return l.patch(e,t).then(f)},g=function(e){return l.delete(e).then(f)},v={login:function(e){return p("login",e)},getUsers:function(){return h("users")},getUser:function(e){return h("users/".concat(e))},getUserStartupKit:function(e,t,n){return d("users/".concat(e,"/blob"),t,n)},getClientStartupKit:function(e,t,n){return d("clients/".concat(e,"/blob"),t,n)},getOverseerStartupKit:function(e,t){return d("overseer/blob",e,t)},getServerStartupKit:function(e,t,n){return d("servers/".concat(e,"/blob"),t,n)},getClients:function(){return h("clients")},getProject:function(){return h("project")},postUser:function(e){return p("users",e)},patchUser:function(e,t){return m("users/".concat(e),t)},deleteUser:function(e){return g("users/".concat(e))},postClient:function(e){return p("clients",e)},patchClient:function(e,t){return m("clients/".concat(e),t)},deleteClient:function(e){return g("clients/".concat(e))},patchProject:function(e){return m("project",e)},getServer:function(){return h("server")},patchServer:function(e){return m("server",e)}}},57061:function(e,t,n){"use strict";n.d(t,{Z:function(){return C}});var r=n(50029),i=n(87794),s=n.n(i),o=n(41664),u=n.n(o),a=n(29224),c=n.n(a),l=n(70491),f=n.n(l),h=n(86188),d=n.n(h),p=n(85444),m=p.default.div.withConfig({displayName:"styles__StyledLayout",componentId:"sc-xczy9u-0"})(["overflow:hidden;height:100%;width:100%;margin:0;padding:0;display:flex;flex-wrap:wrap;.menu{height:auto;}.content-header{flex:0 0 80px;}"]),g=p.default.div.withConfig({displayName:"styles__StyledContent",componentId:"sc-xczy9u-1"})(["display:flex;flex-direction:column;flex:1 1 0%;overflow:auto;height:calc(100% - 3rem);.inlineeditlarger{padding:10px;}.inlineedit{padding:10px;margin:-10px;}.content-wrapper{padding:",";min-height:800px;}"],(function(e){return e.theme.spacing.four})),v=n(11163),$=n(84506),M=n(67294),y=n(68253),x=n(13258),S=n.n(x),w=n(5801),j=n.n(w),D=n(89924),b=n(85893),C=function(e){var t=e.children,n=e.headerChildren,i=e.title,o=(0,v.useRouter)(),a=o.pathname,l=o.push,p=$,w=(0,M.useState)(),C=w[0],O=w[1],k=(0,y.Gg)();(0,M.useEffect)((function(){D.y.getProject().then((function(e){O(e.project)}))}),[]);var I=function(){var e=(0,r.Z)(s().mark((function e(){return s().wrap((function(e){for(;;)switch(e.prev=e.next){case 0:(0,y.KY)("none","",-1,0),l("/");case 2:case"end":return e.stop()}}),e)})));return function(){return e.apply(this,arguments)}}();return(0,b.jsxs)(m,{children:[(0,b.jsx)(c(),{app:null===C||void 0===C?void 0:C.short_name,appBarActions:k.user.role>0?(0,b.jsxs)("div",{style:{display:"flex",flexDirection:"row",alignItems:"center",marginRight:10},children:[p.demo&&(0,b.jsx)("div",{children:"DEMO MODE"}),(0,b.jsx)(S(),{parentElement:(0,b.jsx)(j(),{icon:{name:"AccountCircleGenericUser",color:"white",size:22},shape:"circle",variant:"link",className:"logout-link"}),position:"top-right",children:(0,b.jsxs)(b.Fragment,{children:[(0,b.jsx)(x.ActionMenuItem,{label:"Logout",onClick:I}),!1]})})]}):(0,b.jsx)(b.Fragment,{})}),(0,b.jsxs)(d(),{className:"menu",itemMatchPattern:function(e){return e===a},itemRenderer:function(e){var t=e.title,n=e.href;return(0,b.jsx)(u(),{href:n,children:t})},location:a,children:[0==k.user.role&&(0,b.jsxs)(h.MenuContent,{children:[(0,b.jsx)(h.MenuItem,{href:"/",icon:{name:"AccountUser"},title:"Login"}),(0,b.jsx)(h.MenuItem,{href:"/registration-form",icon:{name:"ObjectsClipboardEdit"},title:"User Registration Form"})]}),4==k.user.role&&(0,b.jsxs)(h.MenuContent,{children:[(0,b.jsx)(h.MenuItem,{href:"/",icon:{name:"ViewList"},title:"Project Home"}),(0,b.jsx)(h.MenuItem,{href:"/user-dashboard",icon:{name:"ServerEdit"},title:"My Info"}),(0,b.jsx)(h.MenuItem,{href:"/project-admin-dashboard",icon:{name:"AccountGroupShieldAdd"},title:"Users Dashboard"}),(0,b.jsx)(h.MenuItem,{href:"/site-dashboard",icon:{name:"ConnectionNetworkComputers2"},title:"Client Sites"}),(0,b.jsx)(h.MenuItem,{href:"/project-configuration",icon:{name:"SettingsCog"},title:"Project Configuration"}),(0,b.jsx)(h.MenuItem,{href:"/server-config",icon:{name:"ConnectionServerNetwork1"},title:"Server Configuration"}),(0,b.jsx)(h.MenuItem,{href:"/downloads",icon:{name:"ActionsDownload"},title:"Downloads"}),(0,b.jsx)(h.MenuItem,{href:"/logout",icon:{name:"PlaybackStop"},title:"Logout"})]}),(1==k.user.role||2==k.user.role||3==k.user.role)&&(0,b.jsxs)(h.MenuContent,{children:[(0,b.jsx)(h.MenuItem,{href:"/",icon:{name:"ViewList"},title:"Project Home Page"}),(0,b.jsx)(h.MenuItem,{href:"/user-dashboard",icon:{name:"ServerEdit"},title:"My Info"}),(0,b.jsx)(h.MenuItem,{href:"/downloads",icon:{name:"ActionsDownload"},title:"Downloads"}),(0,b.jsx)(h.MenuItem,{href:"/logout",icon:{name:"PlaybackStop"},title:"Logout"})]}),(0,b.jsx)(h.MenuFooter,{})]}),(0,b.jsxs)(g,{children:[(0,b.jsx)(f(),{className:"content-header",title:i,children:n}),(0,b.jsx)("div",{className:"content-wrapper",children:t})]})]})}},68253:function(e,t,n){"use strict";n.d(t,{Gg:function(){return o},KY:function(){return i},a5:function(){return s}});var r={user:{email:"",token:"",id:-1,role:0},status:"unauthenticated"};function i(e,t,n,i,s){var o=arguments.length>5&&void 0!==arguments[5]&&arguments[5];return r={user:{email:e,token:t,id:n,role:i,org:s},expired:o,status:0==i?"unauthenticated":"authenticated"},localStorage.setItem("session",JSON.stringify(r)),r}function s(e){return r={user:{email:r.user.email,token:r.user.token,id:r.user.id,role:e,org:r.user.org},expired:r.expired,status:r.status},localStorage.setItem("session",JSON.stringify(r)),r}function o(){var e=localStorage.getItem("session");return null!=e&&(r=JSON.parse(e)),r}},50029:function(e,t,n){"use strict";function r(e,t,n,r,i,s,o){try{var u=e[s](o),a=u.value}catch(c){return void n(c)}u.done?t(a):Promise.resolve(a).then(r,i)}function i(e){return function(){var t=this,n=arguments;return new Promise((function(i,s){var o=e.apply(t,n);function u(e){r(o,i,s,u,a,"next",e)}function a(e){r(o,i,s,u,a,"throw",e)}u(void 0)}))}}n.d(t,{Z:function(){return i}})},84506:function(e){"use strict";e.exports=JSON.parse('{"projectname":"New FL Project","demo":false,"url_root":"http://localhost:8443","arraydata":[{"name":"itemone"},{"name":"itemtwo"},{"name":"itemthree"}]}')}}]);