/** @typedef {{id:number,code:string,version:number,name:string,numerator:string,denominator:string,locked:boolean}} Metric */
/** @typedef {{id:number,class_code:string,day:string,mode:string,enrolled:number,attended:number,completed:number,refunds:number}} Fact */
/** @typedef {{id:number,metric_id:number,state:string,result:object,approval:string,note:string}} Snapshot */
/** @typedef {{date_from:string,date_to:string,total:number,label:string}} ReconInterval */
/** @typedef {{id:number,class_code:string,date_from:string,date_to:string,state:string,constraint_spec:object,basis:object|null,analysis:object|null,correction:object|null}} Reconciliation */
