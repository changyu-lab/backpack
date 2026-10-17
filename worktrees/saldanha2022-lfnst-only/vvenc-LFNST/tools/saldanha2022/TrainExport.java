import java.io.*;
import java.nio.file.*;
import java.lang.reflect.*;
import java.util.*;
import weka.classifiers.trees.REPTree;
import weka.core.*;

/** Export genuine WEKA node doubles, never parse its rounded display tree. */
public class TrainExport {
  static Object field(Object o,String name) throws Exception {
    Class<?> c=o.getClass();
    while(c!=null) { try { Field f=c.getDeclaredField(name); f.setAccessible(true); return f.get(o); } catch(NoSuchFieldException e) { c=c.getSuperclass(); } }
    throw new NoSuchFieldException(name);
  }
  static class Node { int feature,left=-1,right=-1; double threshold=0,weight=0; double[] probs; }
  static ArrayList<Node> nodes=new ArrayList<>();
  static int visit(Object tree) throws Exception {
    Node n=new Node(); int id=nodes.size(); nodes.add(n);
    n.feature=(Integer)field(tree,"m_Attribute"); n.probs=(double[])field(tree,"m_ClassProbs");
    if(n.probs==null) throw new IllegalStateException("Unsupported empty WEKA distribution; refusing lossy export");
    if(n.feature>=0) {
      n.threshold=(Double)field(tree,"m_SplitPoint"); n.weight=((double[])field(tree,"m_Prop"))[0];
      Object[] children=(Object[])field(tree,"m_Successors");
      if(children.length!=2) throw new IllegalStateException("Only numeric binary splits supported");
      n.left=visit(children[0]); n.right=visit(children[1]);
    }
    return id;
  }
  static double[] predict(int id,Instance x) {
    Node n=nodes.get(id); if(n.feature<0) return n.probs.clone();
    if(x.isMissing(n.feature)) { double[] a=predict(n.left,x),b=predict(n.right,x); return new double[]{n.weight*a[0]+(1-n.weight)*b[0],n.weight*a[1]+(1-n.weight)*b[1]}; }
    return predict(x.value(n.feature)<n.threshold?n.left:n.right,x);
  }
  static void verify(REPTree model,Instance x) throws Exception {
    double[] a=model.distributionForInstance(x),b=predict(0,x);
    for(int i=0;i<2;i++) if(Math.abs(a[i]-b[i])>1e-12) throw new AssertionError("Export prediction differs: "+Arrays.toString(a)+" / "+Arrays.toString(b));
  }
  static boolean reaches(int target, Instance x) {
    int id=0;
    while(true) { if(id==target)return true; Node n=nodes.get(id); if(n.feature<0 || x.isMissing(n.feature))return false; id=x.value(n.feature)<n.threshold?n.left:n.right; }
  }
  public static void main(String[] args) throws Exception {
    Instances train=new Instances(new BufferedReader(new FileReader(args[0]))); train.setClassIndex(train.numAttributes()-1);
    Instances validation=new Instances(new BufferedReader(new FileReader(args[1]))); validation.setClassIndex(validation.numAttributes()-1);
    REPTree model=new REPTree(); model.setMaxDepth(8); model.setSeed(Integer.parseInt(args[3])); model.buildClassifier(train);
    visit(field(model,"m_Tree")); Path out=Paths.get(args[2]);
    try(PrintWriter w=new PrintWriter(out.resolve("model.txt").toFile(),"UTF-8")) {
      w.println("LFNST_REPTREE_V1 13 "+nodes.size());
      for(int id=0;id<nodes.size();id++) { Node n=nodes.get(id); w.println(id+" "+n.feature+" "+n.threshold+" "+n.left+" "+n.right+" "+n.weight+" "+n.probs[0]+" "+n.probs[1]); }
    }
    int probes=0;
    for(int i=0;i<train.numInstances();i++) { verify(model,train.instance(i)); probes++; }
    // Every threshold is checked below, at and above, plus NaN using real WEKA inference.
    try(PrintWriter w=new PrintWriter(out.resolve("probes.csv").toFile(),"UTF-8")) {
      for(int f=0;f<13;f++) w.print(train.attribute(f).name()+","); w.println("p0,p1,target_node,kind");
      for(int id=0;id<nodes.size();id++) { Node n=nodes.get(id); if(n.feature<0)continue;
        for(double v:new double[]{Math.nextDown(n.threshold),n.threshold,Math.nextUp(n.threshold)}) {
          Instance witness=null;
          for(int i=0;i<train.numInstances();i++) { Instance x=(Instance)train.instance(i).copy(); x.setValue(n.feature,v); if(reaches(id,x)){witness=x;break;} }
          if(witness==null) throw new AssertionError("No reachable boundary witness for node "+id+" value "+v);
          verify(model,witness); probes++; double[] p=model.distributionForInstance(witness);
          for(int f=0;f<13;f++)w.print(witness.value(f)+","); w.println(p[0]+","+p[1]+","+id+",boundary");
          Instance missing=(Instance)witness.copy(); missing.setMissing(n.feature); verify(model,missing); probes++;
        }
      }
    }
    try(PrintWriter w=new PrintWriter(out.resolve("weka_predictions.csv").toFile(),"UTF-8")) {
      w.println("p0,p1");
      for(int i=0;i<validation.numInstances();i++) { Instance x=validation.instance(i); verify(model,x); double[] p=model.distributionForInstance(x); w.println(p[0]+","+p[1]); probes++; }
    }
    SerializationHelper.write(out.resolve("weka.model").toString(),model);
    Files.writeString(out.resolve("weka_tree.txt"),model.toString());
    Files.writeString(out.resolve("equivalence.json"),"{\"probe_count\":"+probes+",\"tolerance\":1e-12,\"passed\":true}\n");
  }
}
