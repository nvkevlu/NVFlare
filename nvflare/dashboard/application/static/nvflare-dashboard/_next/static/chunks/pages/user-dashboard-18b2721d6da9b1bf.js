(self.webpackChunk_N_E=self.webpackChunk_N_E||[]).push([[442],{89924:function(e,n,t){"use strict";t.d(n,{y:function(){return v}});var r=t(9669),i=t.n(r),o=t(84506),a=t(68253),s=t(35823),c=t.n(s),l=o,u=i().create({baseURL:l.url_root+"/api/v1/",headers:{"Access-Control-Allow-Origin":"*"}});u.interceptors.request.use((function(e){return e.headers.Authorization="Bearer "+(0,a.Gg)().user.token,e}),(function(e){console.log("Interceptor request error: "+e)})),u.interceptors.response.use((function(e){return e}),(function(e){throw console.log(" AXIOS error: "),console.log(e),401===e.response.status&&(0,a.KY)("","",-1,0,"",!0),403===e.response.status&&console.log("Error: "+e.response.data.status),404===e.response.status&&console.log("Error: "+e.response.data.status),409===e.response.status&&console.log("Error: "+e.response.data.status),422===e.response.status&&(0,a.KY)("","",-1,0,"",!0),e}));var d=function(e){return e.data},p=function(e){return u.get(e).then(d)},f=function(e,n,t){return u.post(e,{pin:t},{responseType:"blob"}).then((function(e){n=e.headers["content-disposition"].split('"')[1],c()(e.data,n)}))},m=function(e,n){return u.post(e,n).then(d)},h=function(e,n){return u.patch(e,n).then(d)},g=function(e){return u.delete(e).then(d)},v={login:function(e){return m("login",e)},getUsers:function(){return p("users")},getUser:function(e){return p("users/".concat(e))},getUserStartupKit:function(e,n,t){return f("users/".concat(e,"/blob"),n,t)},getClientStartupKit:function(e,n,t){return f("clients/".concat(e,"/blob"),n,t)},getOverseerStartupKit:function(e,n){return f("overseer/blob",e,n)},getServerStartupKit:function(e,n,t){return f("servers/".concat(e,"/blob"),n,t)},getClients:function(){return p("clients")},getProject:function(){return p("project")},postUser:function(e){return m("users",e)},patchUser:function(e,n){return h("users/".concat(e),n)},deleteUser:function(e){return g("users/".concat(e))},postClient:function(e){return m("clients",e)},patchClient:function(e,n){return h("clients/".concat(e),n)},deleteClient:function(e){return g("clients/".concat(e))},patchProject:function(e){return h("project",e)},getServer:function(){return p("server")},patchServer:function(e){return h("server",e)}}},57061:function(e,n,t){"use strict";t.d(n,{Z:function(){return O}});var r=t(50029),i=t(87794),o=t.n(i),a=t(41664),s=t.n(a),c=t(29224),l=t.n(c),u=t(70491),d=t.n(u),p=t(86188),f=t.n(p),m=t(85444),h=m.default.div.withConfig({displayName:"styles__StyledLayout",componentId:"sc-xczy9u-0"})(["overflow:hidden;height:100%;width:100%;margin:0;padding:0;display:flex;flex-wrap:wrap;.menu{height:auto;}.content-header{flex:0 0 80px;}"]),g=m.default.div.withConfig({displayName:"styles__StyledContent",componentId:"sc-xczy9u-1"})(["display:flex;flex-direction:column;flex:1 1 0%;overflow:auto;height:calc(100% - 3rem);.inlineeditlarger{padding:10px;}.inlineedit{padding:10px;margin:-10px;}.content-wrapper{padding:",";min-height:800px;}"],(function(e){return e.theme.spacing.four})),v=t(11163),_=t(84506),y=t(67294),j=t(68253),x=t(13258),b=t.n(x),w=t(5801),C=t.n(w),S=t(89924),I=t(85893),O=function(e){var n=e.children,t=e.headerChildren,i=e.title,a=(0,v.useRouter)(),c=a.pathname,u=a.push,m=_,w=(0,y.useState)(),O=w[0],k=w[1],P=(0,j.Gg)();(0,y.useEffect)((function(){S.y.getProject().then((function(e){k(e.project)}))}),[]);var N=function(){var e=(0,r.Z)(o().mark((function e(){return o().wrap((function(e){for(;;)switch(e.prev=e.next){case 0:(0,j.KY)("none","",-1,0),u("/");case 2:case"end":return e.stop()}}),e)})));return function(){return e.apply(this,arguments)}}();return(0,I.jsxs)(h,{children:[(0,I.jsx)(l(),{app:null===O||void 0===O?void 0:O.short_name,appBarActions:P.user.role>0?(0,I.jsxs)("div",{style:{display:"flex",flexDirection:"row",alignItems:"center",marginRight:10},children:[m.demo&&(0,I.jsx)("div",{children:"DEMO MODE"}),(0,I.jsx)(b(),{parentElement:(0,I.jsx)(C(),{icon:{name:"AccountCircleGenericUser",color:"white",size:22},shape:"circle",variant:"link",className:"logout-link"}),position:"top-right",children:(0,I.jsxs)(I.Fragment,{children:[(0,I.jsx)(x.ActionMenuItem,{label:"Logout",onClick:N}),!1]})})]}):(0,I.jsx)(I.Fragment,{})}),(0,I.jsxs)(f(),{className:"menu",itemMatchPattern:function(e){return e===c},itemRenderer:function(e){var n=e.title,t=e.href;return(0,I.jsx)(s(),{href:t,children:n})},location:c,children:[0==P.user.role&&(0,I.jsxs)(p.MenuContent,{children:[(0,I.jsx)(p.MenuItem,{href:"/",icon:{name:"AccountUser"},title:"Login"}),(0,I.jsx)(p.MenuItem,{href:"/registration-form",icon:{name:"ObjectsClipboardEdit"},title:"User Registration Form"})]}),4==P.user.role&&(0,I.jsxs)(p.MenuContent,{children:[(0,I.jsx)(p.MenuItem,{href:"/",icon:{name:"ViewList"},title:"Project Home"}),(0,I.jsx)(p.MenuItem,{href:"/user-dashboard",icon:{name:"ServerEdit"},title:"My Info"}),(0,I.jsx)(p.MenuItem,{href:"/project-admin-dashboard",icon:{name:"AccountGroupShieldAdd"},title:"Users Dashboard"}),(0,I.jsx)(p.MenuItem,{href:"/site-dashboard",icon:{name:"ConnectionNetworkComputers2"},title:"Client Sites"}),(0,I.jsx)(p.MenuItem,{href:"/project-configuration",icon:{name:"SettingsCog"},title:"Project Configuration"}),(0,I.jsx)(p.MenuItem,{href:"/server-config",icon:{name:"ConnectionServerNetwork1"},title:"Server Configuration"}),(0,I.jsx)(p.MenuItem,{href:"/downloads",icon:{name:"ActionsDownload"},title:"Downloads"}),(0,I.jsx)(p.MenuItem,{href:"/logout",icon:{name:"PlaybackStop"},title:"Logout"})]}),(1==P.user.role||2==P.user.role||3==P.user.role)&&(0,I.jsxs)(p.MenuContent,{children:[(0,I.jsx)(p.MenuItem,{href:"/",icon:{name:"ViewList"},title:"Project Home Page"}),(0,I.jsx)(p.MenuItem,{href:"/user-dashboard",icon:{name:"ServerEdit"},title:"My Info"}),(0,I.jsx)(p.MenuItem,{href:"/downloads",icon:{name:"ActionsDownload"},title:"Downloads"}),(0,I.jsx)(p.MenuItem,{href:"/logout",icon:{name:"PlaybackStop"},title:"Logout"})]}),(0,I.jsx)(p.MenuFooter,{})]}),(0,I.jsxs)(g,{children:[(0,I.jsx)(d(),{className:"content-header",title:i,children:t}),(0,I.jsx)("div",{className:"content-wrapper",children:n})]})]})}},4636:function(e,n,t){"use strict";t.d(n,{mg:function(){return y},nv:function(){return S}});t(67294);var r=t(85444),i=(t(40398),t(90878)),o=t.n(i),a=t(85893);(0,r.default)(o()).withConfig({displayName:"ErrorMessage__StyledErrorText",componentId:"sc-azomh6-0"})(["display:block;color:",";font-size:",";font-weight:",";position:absolute;"],(function(e){return e.theme.colors.red500}),(function(e){return e.theme.typography.size.small}),(function(e){return e.theme.typography.weight.bold}));r.default.div.withConfig({displayName:"CheckboxField__CheckboxWrapperStyled",componentId:"sc-1m8bzxk-0"})(["align-self:",";display:",";.checkbox-label-wrapper{display:flex;align-items:flex-start;.checkbox-custom-label{margin-left:",";}}.checkbox-text,.checkbox-custom-label{font-size:",";white-space:break-spaces;}"],(function(e){return e.centerVertically?"center":""}),(function(e){return e.centerVertically?"flex":"block"}),(function(e){return e.theme.spacing.one}),(function(e){return e.theme.typography.size.small}));var s=t(59499),c=t(4730),l=t(82175),u=t(32754),d=t.n(u),p=t(57299),f=r.default.div.withConfig({displayName:"InfoMessage__FieldHint",componentId:"sc-s0s5lu-0"})(["display:flex;align-items:center;svg{margin-right:",";}"],(function(e){return e.theme.spacing.one})),m=function(e){var n=e.children;return(0,a.jsxs)(f,{children:[(0,a.jsx)(p.default,{name:"StatusCircleInformation",size:"small"}),n]})},h=r.default.div.withConfig({displayName:"styles__StyledField",componentId:"sc-1fjauag-0"})(["> div{margin-bottom:0px;}margin-bottom:",";"],(function(e){return e.theme.spacing.four})),g=["name","disabled","options","placeholder","info","wrapperClass"];function v(e,n){var t=Object.keys(e);if(Object.getOwnPropertySymbols){var r=Object.getOwnPropertySymbols(e);n&&(r=r.filter((function(n){return Object.getOwnPropertyDescriptor(e,n).enumerable}))),t.push.apply(t,r)}return t}function _(e){for(var n=1;n<arguments.length;n++){var t=null!=arguments[n]?arguments[n]:{};n%2?v(Object(t),!0).forEach((function(n){(0,s.Z)(e,n,t[n])})):Object.getOwnPropertyDescriptors?Object.defineProperties(e,Object.getOwnPropertyDescriptors(t)):v(Object(t)).forEach((function(n){Object.defineProperty(e,n,Object.getOwnPropertyDescriptor(t,n))}))}return e}var y=function(e){var n=e.name,t=e.disabled,r=e.options,i=e.placeholder,o=e.info,s=e.wrapperClass,u=void 0===s?"":s,p=(0,c.Z)(e,g);return(0,a.jsx)(l.gN,{name:n,children:function(e){var s=e.form,c=!!s.errors[n]&&(s.submitCount>0||s.touched[n]);return(0,a.jsxs)(h,{className:u,children:[(0,a.jsx)(d(),_(_({},p),{},{disabled:!!t||s.isSubmitting,name:n,onBlur:function(){return s.setFieldTouched(n,!0)},onChange:function(e){return s.setFieldValue(n,e)},options:r,placeholder:i,valid:!c,validationMessage:c?s.errors[n]:void 0,value:null===s||void 0===s?void 0:s.values[n]})),o&&(0,a.jsx)(m,{children:o})]})}})},j=t(24777),x=t.n(j),b=["className","name","info","label","disabled","placeholder"];function w(e,n){var t=Object.keys(e);if(Object.getOwnPropertySymbols){var r=Object.getOwnPropertySymbols(e);n&&(r=r.filter((function(n){return Object.getOwnPropertyDescriptor(e,n).enumerable}))),t.push.apply(t,r)}return t}function C(e){for(var n=1;n<arguments.length;n++){var t=null!=arguments[n]?arguments[n]:{};n%2?w(Object(t),!0).forEach((function(n){(0,s.Z)(e,n,t[n])})):Object.getOwnPropertyDescriptors?Object.defineProperties(e,Object.getOwnPropertyDescriptors(t)):w(Object(t)).forEach((function(n){Object.defineProperty(e,n,Object.getOwnPropertyDescriptor(t,n))}))}return e}var S=function(e){var n=e.className,t=e.name,r=e.info,i=e.label,o=e.disabled,s=e.placeholder,u=(0,c.Z)(e,b);return(0,a.jsx)(l.gN,{name:t,children:function(e){var c=e.form,l=!!c.errors[t]&&(c.submitCount>0||c.touched[t]);return(0,a.jsxs)(h,{children:[(0,a.jsx)(x(),C(C({},u),{},{className:n,disabled:!!o||c.isSubmitting,label:i,name:t,onBlur:c.handleBlur,onChange:c.handleChange,placeholder:s,valid:!l,validationMessage:l?c.errors[t]:void 0,value:null===c||void 0===c?void 0:c.values[t]})),r&&(0,a.jsx)(m,{children:r})]})}})}},56921:function(e,n,t){"use strict";t.d(n,{P:function(){return l},X:function(){return c}});var r=t(85444),i=t(36578),o=t.n(i),a=t(3159),s=t.n(a),c=(0,r.default)(s()).withConfig({displayName:"form-page__StyledFormExample",componentId:"sc-rfrcq8-0"})([".bottom{display:flex;gap:",";}.zero-left{margin-left:0;}.zero-right{margin-right:0;}"],(function(e){return e.theme.spacing.four})),l=(0,r.default)(o()).withConfig({displayName:"form-page__StyledBanner",componentId:"sc-rfrcq8-1"})(["margin-bottom:1rem;"])},3971:function(e,n,t){"use strict";t.r(n);var r=t(59499),i=t(76687),o=t(57061),a=t(3159),s=t.n(a),c=t(67294),l=t(5801),u=t.n(l),d=t(82175),p=t(90878),f=t.n(p),m=t(30038),h=t.n(m),g=t(74231),v=t(57539),_=t.n(v),y=t(68253),j=t(4636),x=t(56921),b=t(84506),w=t(89924),C=t(11163),S=t(85893),I=_();n.default=function(){var e=(0,y.Gg)(),n=(0,C.useRouter)().push,t=(0,c.useState)(!1),a=t[0],l=t[1],p=(0,c.useState)(),m=p[0],v=p[1],_=(0,c.useState)([]),O=_[0],k=_[1],P=(0,c.useState)({column:"",id:-1}),N=P[0],z=P[1],M=(0,c.useState)(""),A=M[0],B=M[1],E=(0,c.useState)(!1),F=E[0],G=E[1],D=b;(0,c.useEffect)((function(){if(D.demo){var t={approval_state:1,created_at:"Fri, 22 Jul 2022 16:48:27 GMT",description:"",email:"sitemanager@organization1.com",id:5,name:"John",organization:"NVIDIA",organization_id:1,password_hash:"pbkdf2:sha256:260000$93Zo4zK8kvAb6kkA$99038d7da338cdb1bc6227338f178f66cc6d2af3c471460c5b9e6c62d62c4e07",role:"org_admin",role_id:1,sites:[{name:"site-1",id:0,org:"NVIDIA",num_of_gpus:4,approval_state:100,mem_per_gpu_in_GiB:40},{name:"site-2",id:1,org:"NVIDIA",num_of_gpus:2,approval_state:0,mem_per_gpu_in_GiB:16}],updated_at:"Fri, 22 Jul 2022 16:48:27 GMT"};v((function(){return t}))}else w.y.getUser(e.user.id).then((function(e){e&&v(e.user);var n=e.user.organization;w.y.getClients().then((function(e){var t=e.client_list.filter((function(e){return""!==n&&e.organization===n})).map((function(e){var n,t;return{name:e.name,id:e.id,org:e.organization,num_of_gpus:null===(n=e.capacity)||void 0===n?void 0:n.num_of_gpus,mem_per_gpu_in_GiB:null===(t=e.capacity)||void 0===t?void 0:t.mem_per_gpu_in_GiB,approval_state:e.approval_state}}));k(t)})).catch((function(){}))})).catch((function(e){console.log(e),n("/")}))}),[n,e.user.id,e.user.token,D.demo]);var U=function(e){""!=A&&(!function(e,n,t,r){var i=O.map((function(e){return e.id===n?(e[t]=r,e):e}));k(i)}(0,parseInt(e.target.id),e.target.title,A),F?T(A,e.target.title):-1!=parseInt(e.target.id)&&L(parseInt(e.target.id),e.target.title,A),B(""))},T=function(e,n){var t={name:e,organization:"undefined"==typeof m?"":m.organization,capacity:{num_of_gpus:4,mem_per_gpu_in_GiB:16}};w.y.postClient(t).then((function(e){if("ok"==e.status){var t=O.map((function(n){return-1==n.id&&(console.log(n),n.id=e.client.id),n}));k(t)}G(!1),R(n)})).catch((function(e){Z(e)}))},Z=function(e){console.log(e),409==e.response.status?alert("This site name already exists. Please choose another site name."):(alert("Your session may have timed out. Please log in from the home page to add or edit client sites."),n("/"))},K=function(e,n){if("ok"==n.status){var t=O.map((function(t){var r,i;t.id==e&&(t={name:n.client.name,id:n.client.id,org:n.client.organization,num_of_gpus:null===(r=n.client.capacity)||void 0===r?void 0:r.num_of_gpus,mem_per_gpu_in_GiB:null===(i=n.client.capacity)||void 0===i?void 0:i.mem_per_gpu_in_GiB,approval_state:n.client.approval_state});return t}));k(t)}},L=function(e,n,t){if("name"===n)w.y.patchClient(e,(0,r.Z)({},n,t)).then((function(t){K(e,t),R(n)})).catch((function(e){Z(e)}));else if("num_of_gpus"===n){var i,o=null===(i=O.find((function(n){return n.id===e})))||void 0===i?void 0:i.mem_per_gpu_in_GiB;w.y.patchClient(e,{capacity:{num_of_gpus:parseInt(t)>-1?parseInt(t):4,mem_per_gpu_in_GiB:o||0}}).then((function(t){K(e,t),R(n)})).catch((function(e){Z(e)}))}else if("mem_per_gpu_in_GiB"===n){var a,s=null===(a=O.find((function(n){return n.id===e})))||void 0===a?void 0:a.num_of_gpus;w.y.patchClient(e,{capacity:{num_of_gpus:s||0,mem_per_gpu_in_GiB:parseInt(t)>-1?parseInt(t):16}}).then((function(t){K(e,t),R(n)})).catch((function(e){Z(e)}))}},R=function(e){z({column:e,id:-1})},V=(0,c.useCallback)((function(e){e&&e.focus()}),[]),H=[{accessor:"name",Cell:function(e){var n=e.value,t=e.row;return(0,S.jsx)(S.Fragment,{children:"name"==N.column&&N.id==parseInt(t.id)?(0,S.jsx)(S.Fragment,{children:(0,S.jsx)("input",{ref:V,id:t.id,value:A,title:"name",onBlur:function(e){U(e)},placeholder:"site name",onChange:function(e){B(e.target.value)}})}):(0,S.jsx)(S.Fragment,{children:(0,S.jsx)("div",{className:"inlineeditlarger",onClick:function(){t.values.approval_state<=0&&(B(n),z({column:"name",id:parseInt(t.id)}))},children:n||"[none]"})})})}},{accessor:"num_of_gpus",Header:"NUM GPUS",Cell:function(e){var n=e.value,t=e.row;return(0,S.jsx)(S.Fragment,{children:"num_of_gpus"==N.column&&N.id==parseInt(t.id)?(0,S.jsx)(S.Fragment,{children:(0,S.jsx)("input",{ref:V,id:t.id,value:A,title:"num_of_gpus",onBlur:function(e){U(e)},onChange:function(e){B(e.target.value)}})}):(0,S.jsx)(S.Fragment,{children:(0,S.jsx)("div",{className:"inlineeditlarger",onClick:function(){B(n),z({column:"num_of_gpus",id:parseInt(t.id)})},children:n})})})}},{accessor:"mem_per_gpu_in_GiB",Header:"Memory per gpu (GiB)",Cell:function(e){var n=e.value,t=e.row;return(0,S.jsx)(S.Fragment,{children:"mem_per_gpu_in_GiB"==N.column&&N.id==parseInt(t.id)?(0,S.jsx)(S.Fragment,{children:(0,S.jsx)("input",{ref:V,id:t.id,value:A,title:"mem_per_gpu_in_GiB",onBlur:function(e){U(e)},onChange:function(e){B(e.target.value)}})}):(0,S.jsx)(S.Fragment,{children:(0,S.jsx)("div",{className:"inlineeditlarger",onClick:function(){B(n),z({column:"mem_per_gpu_in_GiB",id:parseInt(t.id)})},children:n})})})}},{accessor:"approval_state",Cell:function(e){var n=e.value;return(0,S.jsx)("div",{className:"inlineeditlarger",children:n<0?"Denied":0==n?"Pending":n>=100?"Approved":n})}},{id:"delete",Cell:function(e){var n=e.row;return n.values.approval_state<=0?(0,S.jsx)("div",{children:(0,S.jsx)(u(),{icon:{name:"ActionsTrash",variant:"solid"},onClick:function(){w.y.deleteClient(parseInt(n.id)).then((function(e){"ok"==e.status?k(O.filter((function(e){return e.id!=parseInt(n.id)}))):alert(e.status)})).catch((function(e){console.log(e)}))},shape:"rectangle",size:"regular",tag:"button",type:"critical",variant:"outline",width:"fit-content"})}):(0,S.jsx)("div",{children:(0,S.jsx)(u(),{icon:{name:"ActionsTrash",variant:"solid"},disabled:!0,shape:"rectangle",size:"regular",tag:"button",type:"secondary",variant:"outline",width:"fit-content"})})}}];var J=g.Ry().shape({password:g.Z_(),confirm_password:g.Z_().oneOf([g.iH("password")],"Passwords do not match!").when("password",{is:function(e){return"undefined"!=typeof e&&e.length>0},then:g.Z_().required("Passwords do not match!").oneOf([g.iH("password")],"Passwords do not match!")})});return(0,S.jsx)(o.Z,{title:"User Dashboard",children:m?(0,S.jsxs)(S.Fragment,{children:[(0,S.jsxs)("div",{style:{width:"52rem"},children:[parseInt(m.approval_state.toString())<100&&parseInt(m.approval_state.toString())>-1&&(0,S.jsxs)(x.P,{status:"warning",rounded:!0,children:["Your registration is awaiting approval by the Project Admin. Once approved, you will be able to download your Flare Console","org_admin"==m.role&&" and Client Site Startup Kits"," from the Downloads page."]}),parseInt(m.approval_state.toString())<0&&(0,S.jsx)(x.P,{status:"warning",rounded:!0,children:"Your registration has been denied by the Project Admin."}),(0,S.jsxs)(s(),{title:m.name,actions:(0,S.jsx)(u(),{type:"primary",variant:"outline",onClick:function(){l(!0)},children:"Edit My Profile"}),children:[(0,S.jsx)("div",{style:{fontSize:"1rem"},children:m.email}),(0,S.jsxs)("div",{style:{fontSize:"1rem",marginTop:".25rem"},children:["Organization: ",m.organization]}),(0,S.jsxs)("div",{style:{fontSize:"1rem",marginTop:".25rem",marginBottom:".5rem"},children:["Role: ","org_admin"==m.role?"Org Admin":"member"==m.role?"Member":"lead"==m.role?"Lead":m.role]})]}),3==e.user.role&&(0,S.jsx)(s(),{actions:(0,S.jsx)(u(),{type:"primary",variant:"outline",onClick:function(){k([].concat((0,i.Z)(O),[{name:"",id:-1,org:"undefined"==typeof m?"":m.organization,num_of_gpus:4,mem_per_gpu_in_GiB:16,approval_state:0}])),z({column:"name",id:-1}),B(""),G(!0)},children:"Add Site"}),title:"Client Sites",children:(0,S.jsx)(I,{columns:H,data:O,rowOnClick:function(){},disableFilters:!0,disableExport:!0,getHeaderProps:function(e){return{style:{fontSize:"1rem",fontWeight:"bold"}}},getRowId:function(e,n){return""+e.id}})})]}),(0,S.jsx)(d.J9,{initialValues:m,onSubmit:function(n,t){""!=n.password&&w.y.patchUser(e.user.id,{password:n.password}).then((function(e){t.setSubmitting(!1)}))},validationSchema:J,children:function(e){return(0,S.jsx)(S.Fragment,{children:(0,S.jsx)(h(),{footer:(0,S.jsxs)(S.Fragment,{children:[(0,S.jsx)(u(),{type:"primary",disabled:!e.dirty||!e.isValid||""==e.values.password,onClick:function(){e.handleSubmit(),l(!1)},children:"Save"}),(0,S.jsx)(u(),{type:"secondary",variant:"outline",onClick:function(){l(!1)},children:"Cancel"})]}),onClose:function(){return l(!1)},onDestructiveButtonClick:function(){},onPrimaryButtonClick:function(){},onSecondaryButtonClick:function(){},size:"large",open:a,title:"Edit user details",closeOnBackdropClick:!1,children:(0,S.jsxs)("div",{children:[(0,S.jsx)(f(),{tag:"label",textStyle:"p1",children:"Please contact the project administrator if you need changes to your name, email, or organization."}),(0,S.jsx)("div",{className:"name",style:{display:"flex"},children:(0,S.jsx)(j.nv,{disabled:!0,label:"Name",name:"name",placeholder:"Please enter your name..."})}),(0,S.jsx)(j.nv,{disabled:!0,label:"Email",name:"email",placeholder:""}),(0,S.jsx)(j.nv,{disabled:!0,label:"Organization",name:"organization",placeholder:""}),(0,S.jsxs)("div",{className:"bottom",style:{display:"flex"},children:[(0,S.jsx)("div",{style:{width:"50%"},children:(0,S.jsx)(j.nv,{inputType:"password",label:"Reset user password to:",name:"password",placeholder:""})}),(0,S.jsx)("div",{style:{width:"50%"},children:(0,S.jsx)(j.nv,{inputType:"password",label:"Confirm value to reset password to:",name:"confirm_password",placeholder:""})})]})]})})})}})]}):(0,S.jsx)("span",{children:"loading..."})})}},68253:function(e,n,t){"use strict";t.d(n,{Gg:function(){return a},KY:function(){return i},a5:function(){return o}});var r={user:{email:"",token:"",id:-1,role:0},status:"unauthenticated"};function i(e,n,t,i,o){var a=arguments.length>5&&void 0!==arguments[5]&&arguments[5];return r={user:{email:e,token:n,id:t,role:i,org:o},expired:a,status:0==i?"unauthenticated":"authenticated"},localStorage.setItem("session",JSON.stringify(r)),r}function o(e){return r={user:{email:r.user.email,token:r.user.token,id:r.user.id,role:e,org:r.user.org},expired:r.expired,status:r.status},localStorage.setItem("session",JSON.stringify(r)),r}function a(){var e=localStorage.getItem("session");return null!=e&&(r=JSON.parse(e)),r}},49834:function(e,n,t){(window.__NEXT_P=window.__NEXT_P||[]).push(["/user-dashboard",function(){return t(3971)}])},50029:function(e,n,t){"use strict";function r(e,n,t,r,i,o,a){try{var s=e[o](a),c=s.value}catch(l){return void t(l)}s.done?n(c):Promise.resolve(c).then(r,i)}function i(e){return function(){var n=this,t=arguments;return new Promise((function(i,o){var a=e.apply(n,t);function s(e){r(a,i,o,s,c,"next",e)}function c(e){r(a,i,o,s,c,"throw",e)}s(void 0)}))}}t.d(n,{Z:function(){return i}})},76687:function(e,n,t){"use strict";function r(e,n){(null==n||n>e.length)&&(n=e.length);for(var t=0,r=new Array(n);t<n;t++)r[t]=e[t];return r}function i(e){return function(e){if(Array.isArray(e))return r(e)}(e)||function(e){if("undefined"!==typeof Symbol&&null!=e[Symbol.iterator]||null!=e["@@iterator"])return Array.from(e)}(e)||function(e,n){if(e){if("string"===typeof e)return r(e,n);var t=Object.prototype.toString.call(e).slice(8,-1);return"Object"===t&&e.constructor&&(t=e.constructor.name),"Map"===t||"Set"===t?Array.from(e):"Arguments"===t||/^(?:Ui|I)nt(?:8|16|32)(?:Clamped)?Array$/.test(t)?r(e,n):void 0}}(e)||function(){throw new TypeError("Invalid attempt to spread non-iterable instance.\nIn order to be iterable, non-array objects must have a [Symbol.iterator]() method.")}()}t.d(n,{Z:function(){return i}})},84506:function(e){"use strict";e.exports=JSON.parse('{"projectname":"New FL Project","demo":false,"url_root":"http://localhost:8443","arraydata":[{"name":"itemone"},{"name":"itemtwo"},{"name":"itemthree"}]}')}},function(e){e.O(0,[234,539,897,774,888,179],(function(){return n=49834,e(e.s=n);var n}));var n=e.O();_N_E=n}]);