import ReactFlow,{Background,Controls,Handle,MiniMap,MarkerType,Position,type NodeProps}from'reactflow';
import{Cloud,Globe2,Layers3}from'lucide-react';
import type {Any}from'../types/network';

function ArchitectureNode({data}:NodeProps){return <div className="flow-node"><Handle type="target" id="target-left" position={Position.Left}/><Handle type="target" id="target-top" position={Position.Top}/><div>{data.label}</div><Handle type="source" id="source-right" position={Position.Right}/><Handle type="source" id="source-bottom" position={Position.Bottom}/><Handle type="target" id="target-bottom" position={Position.Bottom}/></div>}
const nodeTypes={architecture:ArchitectureNode};

export default function Topology({result,large=false}:Any){
 const raw=result?.topology||{nodes:[],edges:[]};
 const nodes=(raw.nodes||[]).map((node:Any,i:number)=>({id:node.id,type:'architecture',position:{x:80+i*210,y:large?150:48},data:{label:<div className="flow-label"><span>{node.type==='cloud'?<Cloud size={17}/>:node.type==='router'?<Globe2 size={17}/>:<Layers3 size={17}/>}</span><b>{node.label}</b><small>{node.type}</small></div>}}));
 const edges=(raw.edges||[]).flatMap((edge:Any,i:number)=>{
  const details=`${edge.label}${edge.distance_m?` · ${edge.distance_m.toLocaleString()} m`:''}${edge.bandwidth_gbps?` · ${edge.bandwidth_gbps} Gbps`:''} · ${edge.media}${edge.vlans?.length?` · VLANs ${edge.vlans.join(',')}`:''}`;
  const primary={id:`e-${i}`,source:edge.source,target:edge.target,sourceHandle:'source-right',targetHandle:'target-left',label:details,animated:false,markerEnd:{type:MarkerType.ArrowClosed,color:'#39afd9'},style:{stroke:'#32a9d7',strokeWidth:2},labelStyle:{fill:'#9bb4c7',fontSize:8},labelBgStyle:{fill:'#101925',fillOpacity:.95},type:'smoothstep'};
  return edge.redundant?[primary,{...primary,id:`e-${i}-standby`,sourceHandle:'source-bottom',targetHandle:'target-bottom',label:`${edge.label} · standby path`,animated:true,style:{stroke:'#55c9a5',strokeWidth:1.5,strokeDasharray:'5 4'},labelStyle:{fill:'#78c9ae',fontSize:8}}]:[primary];
 });
 return <div className={`topology flow-canvas ${large?'large':''}`}><ReactFlow nodes={nodes} edges={edges} nodeTypes={nodeTypes} fitView fitViewOptions={{padding:.25}} nodesDraggable nodesConnectable={false} elementsSelectable><Background color="#26384b" gap={22}/><MiniMap nodeColor="#28678a" maskColor="#08101aaa"/><Controls/></ReactFlow><span className="topo-caption"><span className="live-dot"/> INTERACTIVE DESIGN MODEL</span></div>
}

export function topologySvg(result:Any){
 const topo=result?.topology||{nodes:[],edges:[]};const nodes=topo.nodes||[];const width=Math.max(720,nodes.length*180);
 const safe=(value:any)=>String(value??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;');
 const positions=new Map(nodes.map((node:Any,i:number)=>[node.id,{x:70+i*180,y:125}]));
 const paths=(topo.edges||[]).map((edge:Any)=>{const a:any=positions.get(edge.source),b:any=positions.get(edge.target);if(!a||!b)return '';const label=`${edge.label}${edge.distance_m?` · ${edge.distance_m} m`:''}${edge.bandwidth_gbps?` · ${edge.bandwidth_gbps} Gbps`:''} · ${edge.media}${edge.vlans?.length?` · VLANs ${edge.vlans.join(',')}`:''}`;return `<g><path d="M ${a.x+120} ${a.y} L ${b.x} ${b.y}" stroke="#34b8e8" stroke-width="2"/><text x="${(a.x+b.x)/2}" y="${a.y-12}" fill="#91a7ba" text-anchor="middle" font-size="10">${safe(label)}</text>${edge.redundant?`<path d="M ${a.x+120} ${a.y+9} L ${b.x} ${b.y+9}" stroke="#55c9a5" stroke-width="1.5" stroke-dasharray="5 4"/>`:''}</g>`}).join('');
 const boxes=nodes.map((node:Any,i:number)=>{const x=70+i*180;return `<g><rect x="${x}" y="92" width="120" height="66" rx="11" fill="#121f2f" stroke="#31465d"/><text x="${x+60}" y="121" fill="#e6eff9" text-anchor="middle" font-family="sans-serif" font-size="12">${safe(node.label)}</text><text x="${x+60}" y="141" fill="#8c9bad" text-anchor="middle" font-size="10">${safe(node.type)}</text></g>`}).join('');
 return `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="250" viewBox="0 0 ${width} 250"><rect width="100%" height="100%" fill="#0c1420"/>${paths}${boxes}</svg>`;
}
