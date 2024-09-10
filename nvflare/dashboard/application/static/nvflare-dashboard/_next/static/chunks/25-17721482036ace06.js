"use strict";(self.webpackChunk_N_E=self.webpackChunk_N_E||[]).push([[25],{89924:function(e,t,n){n.d(t,{y:function(){return b}});var r=n(9669),o=n.n(r),i=n(84506),s=n(68253),a=n(35823),c=n.n(a),u=i,l=o().create({baseURL:u.url_root+"/api/v1/",headers:{"Access-Control-Allow-Origin":"*"}});l.interceptors.request.use((function(e){return e.headers.Authorization="Bearer "+(0,s.Gg)().user.token,e}),(function(e){console.log("Interceptor request error: "+e)})),l.interceptors.response.use((function(e){return e}),(function(e){throw console.log(" AXIOS error: "),console.log(e),401===e.response.status&&(0,s.KY)("","",-1,0,"",!0),403===e.response.status&&console.log("Error: "+e.response.data.status),404===e.response.status&&console.log("Error: "+e.response.data.status),409===e.response.status&&console.log("Error: "+e.response.data.status),422===e.response.status&&(0,s.KY)("","",-1,0,"",!0),e}));var d=function(e){return e.data},f=function(e){return l.get(e).then(d)},p=function(e,t,n){return l.post(e,{pin:n},{responseType:"blob"}).then((function(e){t=e.headers["content-disposition"].split('"')[1],c()(e.data,t)}))},h=function(e,t){return l.post(e,t).then(d)},g=function(e,t){return l.patch(e,t).then(d)},m=function(e){return l.delete(e).then(d)},b={login:function(e){return h("login",e)},getUsers:function(){return f("users")},getUser:function(e){return f("users/".concat(e))},getUserStartupKit:function(e,t,n){return p("users/".concat(e,"/blob"),t,n)},getClientStartupKit:function(e,t,n){return p("clients/".concat(e,"/blob"),t,n)},getOverseerStartupKit:function(e,t){return p("overseer/blob",e,t)},getServerStartupKit:function(e,t,n){return p("servers/".concat(e,"/blob"),t,n)},getClients:function(){return f("clients")},getProject:function(){return f("project")},postUser:function(e){return h("users",e)},patchUser:function(e,t){return g("users/".concat(e),t)},deleteUser:function(e){return m("users/".concat(e))},postClient:function(e){return h("clients",e)},patchClient:function(e,t){return g("clients/".concat(e),t)},deleteClient:function(e){return m("clients/".concat(e))},patchProject:function(e){return g("project",e)},getServer:function(){return f("server")},patchServer:function(e){return g("server",e)}}},88001:function(e,t,n){n.d(t,{Z:function(){return y}});var r=n(41664),o=n.n(r),i=n(29224),s=n.n(i),a=n(70491),c=n.n(a),u=n(86188),l=n.n(u),d=n(85444),f=d.default.div.withConfig({displayName:"styles__StyledLayout",componentId:"sc-y3h7zi-0"})(["overflow:hidden;height:100%;width:100%;margin:0;padding:0;display:flex;flex-wrap:wrap;.menu{height:auto;}.content-header{flex:0 0 80px;}"]),p=d.default.div.withConfig({displayName:"styles__StyledContent",componentId:"sc-y3h7zi-1"})(["display:flex;flex-direction:column;flex:1 1 0%;overflow:auto;height:calc(100% - 3rem);.inlineeditlarger{padding:10px;}.inlineedit{padding:10px;margin:-10px;}.content-wrapper{padding:",";min-height:800px;}"],(function(e){return e.theme.spacing.four})),h=n(11163),g=(n(84506),n(67294)),m=n(68253),b=n(89924),v=n(85893),y=function(e){var t=e.children,n=e.headerChildren,r=e.title,i=(0,h.useRouter)(),a=i.pathname,u=(i.push,(0,g.useState)()),d=u[0],y=u[1];(0,m.Gg)();return(0,g.useEffect)((function(){b.y.getProject().then((function(e){y(e.project)}))}),[]),(0,v.jsxs)(f,{children:[(0,v.jsx)(s(),{app:null===d||void 0===d?void 0:d.short_name}),(0,v.jsx)(l(),{className:"menu",itemMatchPattern:function(e){return e===a},itemRenderer:function(e){var t=e.title,n=e.href;return(0,v.jsx)(o(),{href:n,children:t})},location:a}),(0,v.jsxs)(p,{children:[(0,v.jsx)(c(),{className:"content-header",title:r,children:n}),(0,v.jsx)("div",{className:"content-wrapper",children:t})]})]})}},4636:function(e,t,n){n.d(t,{mg:function(){return y},nv:function(){return C}});n(67294);var r=n(85444),o=(n(40398),n(90878)),i=n.n(o),s=n(85893);(0,r.default)(i()).withConfig({displayName:"ErrorMessage__StyledErrorText",componentId:"sc-azomh6-0"})(["display:block;color:",";font-size:",";font-weight:",";position:absolute;"],(function(e){return e.theme.colors.red500}),(function(e){return e.theme.typography.size.small}),(function(e){return e.theme.typography.weight.bold}));r.default.div.withConfig({displayName:"CheckboxField__CheckboxWrapperStyled",componentId:"sc-1m8bzxk-0"})(["align-self:",";display:",";.checkbox-label-wrapper{display:flex;align-items:flex-start;.checkbox-custom-label{margin-left:",";}}.checkbox-text,.checkbox-custom-label{font-size:",";white-space:break-spaces;}"],(function(e){return e.centerVertically?"center":""}),(function(e){return e.centerVertically?"flex":"block"}),(function(e){return e.theme.spacing.one}),(function(e){return e.theme.typography.size.small}));var a=n(59499),c=n(4730),u=n(82175),l=n(32754),d=n.n(l),f=n(57299),p=r.default.div.withConfig({displayName:"InfoMessage__FieldHint",componentId:"sc-s0s5lu-0"})(["display:flex;align-items:center;svg{margin-right:",";}"],(function(e){return e.theme.spacing.one})),h=function(e){var t=e.children;return(0,s.jsxs)(p,{children:[(0,s.jsx)(f.default,{name:"StatusCircleInformation",size:"small"}),t]})},g=r.default.div.withConfig({displayName:"styles__StyledField",componentId:"sc-1fjauag-0"})(["> div{margin-bottom:0px;}margin-bottom:",";"],(function(e){return e.theme.spacing.four})),m=["name","disabled","options","placeholder","info","wrapperClass"];function b(e,t){var n=Object.keys(e);if(Object.getOwnPropertySymbols){var r=Object.getOwnPropertySymbols(e);t&&(r=r.filter((function(t){return Object.getOwnPropertyDescriptor(e,t).enumerable}))),n.push.apply(n,r)}return n}function v(e){for(var t=1;t<arguments.length;t++){var n=null!=arguments[t]?arguments[t]:{};t%2?b(Object(n),!0).forEach((function(t){(0,a.Z)(e,t,n[t])})):Object.getOwnPropertyDescriptors?Object.defineProperties(e,Object.getOwnPropertyDescriptors(n)):b(Object(n)).forEach((function(t){Object.defineProperty(e,t,Object.getOwnPropertyDescriptor(n,t))}))}return e}var y=function(e){var t=e.name,n=e.disabled,r=e.options,o=e.placeholder,i=e.info,a=e.wrapperClass,l=void 0===a?"":a,f=(0,c.Z)(e,m);return(0,s.jsx)(u.gN,{name:t,children:function(e){var a=e.form,c=!!a.errors[t]&&(a.submitCount>0||a.touched[t]);return(0,s.jsxs)(g,{className:l,children:[(0,s.jsx)(d(),v(v({},f),{},{disabled:!!n||a.isSubmitting,name:t,onBlur:function(){return a.setFieldTouched(t,!0)},onChange:function(e){return a.setFieldValue(t,e)},options:r,placeholder:o,valid:!c,validationMessage:c?a.errors[t]:void 0,value:null===a||void 0===a?void 0:a.values[t]})),i&&(0,s.jsx)(h,{children:i})]})}})},j=n(24777),x=n.n(j),O=["className","name","info","label","disabled","placeholder"];function w(e,t){var n=Object.keys(e);if(Object.getOwnPropertySymbols){var r=Object.getOwnPropertySymbols(e);t&&(r=r.filter((function(t){return Object.getOwnPropertyDescriptor(e,t).enumerable}))),n.push.apply(n,r)}return n}function S(e){for(var t=1;t<arguments.length;t++){var n=null!=arguments[t]?arguments[t]:{};t%2?w(Object(n),!0).forEach((function(t){(0,a.Z)(e,t,n[t])})):Object.getOwnPropertyDescriptors?Object.defineProperties(e,Object.getOwnPropertyDescriptors(n)):w(Object(n)).forEach((function(t){Object.defineProperty(e,t,Object.getOwnPropertyDescriptor(n,t))}))}return e}var C=function(e){var t=e.className,n=e.name,r=e.info,o=e.label,i=e.disabled,a=e.placeholder,l=(0,c.Z)(e,O);return(0,s.jsx)(u.gN,{name:n,children:function(e){var c=e.form,u=!!c.errors[n]&&(c.submitCount>0||c.touched[n]);return(0,s.jsxs)(g,{children:[(0,s.jsx)(x(),S(S({},l),{},{className:t,disabled:!!i||c.isSubmitting,label:o,name:n,onBlur:c.handleBlur,onChange:c.handleChange,placeholder:a,valid:!u,validationMessage:u?c.errors[n]:void 0,value:null===c||void 0===c?void 0:c.values[n]})),r&&(0,s.jsx)(h,{children:r})]})}})}},56921:function(e,t,n){n.d(t,{P:function(){return u},X:function(){return c}});var r=n(85444),o=n(36578),i=n.n(o),s=n(3159),a=n.n(s),c=(0,r.default)(a()).withConfig({displayName:"form-page__StyledFormExample",componentId:"sc-rfrcq8-0"})([".bottom{display:flex;gap:",";}.zero-left{margin-left:0;}.zero-right{margin-right:0;}"],(function(e){return e.theme.spacing.four})),u=(0,r.default)(i()).withConfig({displayName:"form-page__StyledBanner",componentId:"sc-rfrcq8-1"})(["margin-bottom:1rem;"])},68253:function(e,t,n){n.d(t,{Gg:function(){return s},KY:function(){return o},a5:function(){return i}});var r={user:{email:"",token:"",id:-1,role:0},status:"unauthenticated"};function o(e,t,n,o,i){var s=arguments.length>5&&void 0!==arguments[5]&&arguments[5];return r={user:{email:e,token:t,id:n,role:o,org:i},expired:s,status:0==o?"unauthenticated":"authenticated"},localStorage.setItem("session",JSON.stringify(r)),r}function i(e){return r={user:{email:r.user.email,token:r.user.token,id:r.user.id,role:e,org:r.user.org},expired:r.expired,status:r.status},localStorage.setItem("session",JSON.stringify(r)),r}function s(){var e=localStorage.getItem("session");return null!=e&&(r=JSON.parse(e)),r}},84506:function(e){e.exports=JSON.parse('{"projectname":"New FL Project","demo":false,"url_root":"http://localhost:8443","arraydata":[{"name":"itemone"},{"name":"itemtwo"},{"name":"itemthree"}]}')}}]);