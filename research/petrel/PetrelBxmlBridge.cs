using System;
using System.IO;
using System.Reflection;
using System.Text;
using System.Xml;
using System.Collections.Generic;
using System.Globalization;

internal static class PetrelBxmlBridge
{
    private static int Main(string[] args)
    {
        if (args.Length == 4 && args[0] == "--profile")
        {
            return ProfileFile(args[1], args[2], args[3]);
        }
        if (args.Length == 3 && args[0] == "--batch")
        {
            return ConvertBatch(args[1], args[2]);
        }
        if (args.Length != 3)
        {
            Console.Error.WriteLine("Usage: PetrelBxmlBridge <persistence.dll> <input.bxml> <output.xml>");
            Console.Error.WriteLine("   or: PetrelBxmlBridge --batch <persistence.dll> <manifest.tsv>");
            return 2;
        }

        try
        {
            MethodInfo factory = LoadFactory(args[0]);
            ConvertFile(factory, args[1], args[2]);
            return 0;
        }
        catch (Exception error)
        {
            Console.Error.WriteLine(error);
            return 1;
        }
    }

    private sealed class PathStats
    {
        public long Elements;
        public long TextValues;
        public long TextCharacters;
        public long NumericValues;
        public double Minimum = Double.PositiveInfinity;
        public double Maximum = Double.NegativeInfinity;
        public double Sum;
        public long BoundedNumericValues;
        public double BoundedMinimum = Double.PositiveInfinity;
        public double BoundedMaximum = Double.NegativeInfinity;
        public double BoundedSum;
        public long BinaryBytes;
        public long BinaryZeroBytes;
        public int BinaryMinimum = 256;
        public int BinaryMaximum = -1;
        public double BinarySum;
        public int ComponentWidth;
        public long ComponentIndex;
        public readonly long[] ComponentCounts = new long[3];
        public readonly double[] ComponentMinimum = { Double.PositiveInfinity, Double.PositiveInfinity, Double.PositiveInfinity };
        public readonly double[] ComponentMaximum = { Double.NegativeInfinity, Double.NegativeInfinity, Double.NegativeInfinity };
        public readonly double[] ComponentSum = new double[3];
        public readonly List<string> Samples = new List<string>();
        public readonly List<string> AttributeSamples = new List<string>();
    }

    private static int ProfileFile(string assemblyPath, string inputPath, string outputPath)
    {
        try
        {
            MethodInfo factory = LoadFactory(assemblyPath);
            Dictionary<string, PathStats> stats = new Dictionary<string, PathStats>();
            List<string> names = new List<string>();
            using (FileStream input = File.OpenRead(inputPath))
            using (XmlDictionaryReader reader = (XmlDictionaryReader)factory.Invoke(null, new object[] { input }))
            {
                while (reader.Read())
                {
                    if (reader.NodeType == XmlNodeType.Element)
                    {
                        while (names.Count <= reader.Depth)
                            names.Add(String.Empty);
                        names[reader.Depth] = reader.LocalName;
                        string path = BuildPath(names, reader.Depth);
                        PathStats item = GetStats(stats, path);
                        Type arrayType;
                        if (path.EndsWith("/position/double", StringComparison.Ordinal))
                            item.ComponentWidth = 2;
                        else if (path.EndsWith("/vertices/double", StringComparison.Ordinal))
                            item.ComponentWidth = 3;
                        if (reader.IsStartArray(out arrayType) && ProfileNumericArray(reader, arrayType, item))
                            continue;
                        item.Elements++;
                        if (reader.HasAttributes && item.AttributeSamples.Count < 3)
                        {
                            List<string> attributes = new List<string>();
                            for (int index = 0; index < reader.AttributeCount; index++)
                            {
                                reader.MoveToAttribute(index);
                                attributes.Add(reader.Name + "=" + reader.Value);
                            }
                            reader.MoveToElement();
                            item.AttributeSamples.Add(String.Join(";", attributes.ToArray()));
                        }
                    }
                    else if (reader.NodeType == XmlNodeType.Text)
                    {
                        string path = BuildPath(names, reader.Depth - 1);
                        PathStats item = GetStats(stats, path);
                        string value = reader.Value;
                        item.TextValues++;
                        item.TextCharacters += value.Length;
                        if (path.EndsWith("/page", StringComparison.Ordinal) && value.Length > 200)
                            AddBase64Bytes(item, value);
                        double number;
                        if (Double.TryParse(value, NumberStyles.Float, CultureInfo.InvariantCulture, out number))
                        {
                            item.NumericValues++;
                            item.Minimum = Math.Min(item.Minimum, number);
                            item.Maximum = Math.Max(item.Maximum, number);
                            item.Sum += number;
                            if (!Double.IsNaN(number) && !Double.IsInfinity(number) && Math.Abs(number) < 1.0E19)
                            {
                                item.BoundedNumericValues++;
                                item.BoundedMinimum = Math.Min(item.BoundedMinimum, number);
                                item.BoundedMaximum = Math.Max(item.BoundedMaximum, number);
                                item.BoundedSum += number;
                            }
                        }
                        if (value.Length <= 200 && item.Samples.Count < 8)
                            item.Samples.Add(value);
                    }
                }
            }

            Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(outputPath)));
            using (StreamWriter output = new StreamWriter(outputPath, false, new UTF8Encoding(false)))
            {
                output.WriteLine("path\telements\ttext_values\ttext_characters\tnumeric_values\tminimum\tmaximum\tmean\tbounded_numeric_values\tbounded_minimum\tbounded_maximum\tbounded_mean\tbinary_bytes\tbinary_zero_bytes\tbinary_minimum\tbinary_maximum\tbinary_mean\tcomponent_width\tcomponent_counts\tcomponent_minimum\tcomponent_maximum\tcomponent_mean\tsamples\tattributes");
                foreach (KeyValuePair<string, PathStats> pair in stats)
                {
                    PathStats item = pair.Value;
                    string minimum = item.NumericValues > 0 ? item.Minimum.ToString("R", CultureInfo.InvariantCulture) : String.Empty;
                    string maximum = item.NumericValues > 0 ? item.Maximum.ToString("R", CultureInfo.InvariantCulture) : String.Empty;
                    string mean = item.NumericValues > 0 ? (item.Sum / item.NumericValues).ToString("R", CultureInfo.InvariantCulture) : String.Empty;
                    string boundedMinimum = item.BoundedNumericValues > 0 ? item.BoundedMinimum.ToString("R", CultureInfo.InvariantCulture) : String.Empty;
                    string boundedMaximum = item.BoundedNumericValues > 0 ? item.BoundedMaximum.ToString("R", CultureInfo.InvariantCulture) : String.Empty;
                    string boundedMean = item.BoundedNumericValues > 0 ? (item.BoundedSum / item.BoundedNumericValues).ToString("R", CultureInfo.InvariantCulture) : String.Empty;
                    string binaryMinimum = item.BinaryBytes > 0 ? item.BinaryMinimum.ToString() : String.Empty;
                    string binaryMaximum = item.BinaryBytes > 0 ? item.BinaryMaximum.ToString() : String.Empty;
                    string binaryMean = item.BinaryBytes > 0 ? (item.BinarySum / item.BinaryBytes).ToString("R", CultureInfo.InvariantCulture) : String.Empty;
                    string componentCounts = JoinComponents(item, delegate(int index) { return item.ComponentCounts[index].ToString(); });
                    string componentMinimum = JoinComponents(item, delegate(int index) { return item.ComponentMinimum[index].ToString("R", CultureInfo.InvariantCulture); });
                    string componentMaximum = JoinComponents(item, delegate(int index) { return item.ComponentMaximum[index].ToString("R", CultureInfo.InvariantCulture); });
                    string componentMean = JoinComponents(item, delegate(int index) { return (item.ComponentSum[index] / item.ComponentCounts[index]).ToString("R", CultureInfo.InvariantCulture); });
                    output.WriteLine(String.Join("\t", new[] {
                        Escape(pair.Key), item.Elements.ToString(), item.TextValues.ToString(), item.TextCharacters.ToString(),
                        item.NumericValues.ToString(), minimum, maximum, mean,
                        item.BoundedNumericValues.ToString(), boundedMinimum, boundedMaximum, boundedMean,
                        item.BinaryBytes.ToString(), item.BinaryZeroBytes.ToString(), binaryMinimum, binaryMaximum, binaryMean,
                        item.ComponentWidth.ToString(), componentCounts, componentMinimum, componentMaximum, componentMean,
                        Escape(String.Join(" | ", item.Samples.ToArray())),
                        Escape(String.Join(" | ", item.AttributeSamples.ToArray()))
                    }));
                }
            }
            return 0;
        }
        catch (Exception error)
        {
            Console.Error.WriteLine(error);
            return 1;
        }
    }

    private static PathStats GetStats(Dictionary<string, PathStats> stats, string path)
    {
        PathStats item;
        if (!stats.TryGetValue(path, out item))
        {
            item = new PathStats();
            stats.Add(path, item);
        }
        return item;
    }

    private static bool ProfileNumericArray(XmlDictionaryReader reader, Type arrayType, PathStats stats)
    {
        string localName = reader.LocalName;
        string namespaceUri = reader.NamespaceURI;
        const int BufferSize = 65536;
        if (arrayType == typeof(float))
        {
            float[] values = new float[BufferSize];
            int count;
            while ((count = reader.ReadArray(localName, namespaceUri, values, 0, values.Length)) > 0)
                AddNumbers(stats, values, count);
            return true;
        }
        if (arrayType == typeof(double))
        {
            double[] values = new double[BufferSize];
            int count;
            while ((count = reader.ReadArray(localName, namespaceUri, values, 0, values.Length)) > 0)
                AddNumbers(stats, values, count);
            return true;
        }
        if (arrayType == typeof(int))
        {
            int[] values = new int[BufferSize];
            int count;
            while ((count = reader.ReadArray(localName, namespaceUri, values, 0, values.Length)) > 0)
                AddNumbers(stats, values, count);
            return true;
        }
        if (arrayType == typeof(long))
        {
            long[] values = new long[BufferSize];
            int count;
            while ((count = reader.ReadArray(localName, namespaceUri, values, 0, values.Length)) > 0)
                AddNumbers(stats, values, count);
            return true;
        }
        if (arrayType == typeof(short))
        {
            short[] values = new short[BufferSize];
            int count;
            while ((count = reader.ReadArray(localName, namespaceUri, values, 0, values.Length)) > 0)
                AddNumbers(stats, values, count);
            return true;
        }
        return false;
    }

    private static void AddNumbers(PathStats stats, float[] values, int count)
    {
        for (int index = 0; index < count; index++)
            AddNumber(stats, values[index]);
    }

    private static void AddNumbers(PathStats stats, double[] values, int count)
    {
        for (int index = 0; index < count; index++)
            AddNumber(stats, values[index]);
    }

    private static void AddNumbers(PathStats stats, int[] values, int count)
    {
        for (int index = 0; index < count; index++)
            AddNumber(stats, values[index]);
    }

    private static void AddNumbers(PathStats stats, long[] values, int count)
    {
        for (int index = 0; index < count; index++)
            AddNumber(stats, values[index]);
    }

    private static void AddNumbers(PathStats stats, short[] values, int count)
    {
        for (int index = 0; index < count; index++)
            AddNumber(stats, values[index]);
    }

    private static void AddNumber(PathStats stats, double value)
    {
        stats.Elements++;
        stats.TextValues++;
        stats.NumericValues++;
        stats.Minimum = Math.Min(stats.Minimum, value);
        stats.Maximum = Math.Max(stats.Maximum, value);
        stats.Sum += value;
        if (stats.ComponentWidth > 0)
        {
            int component = (int)(stats.ComponentIndex % stats.ComponentWidth);
            stats.ComponentIndex++;
            stats.ComponentCounts[component]++;
            stats.ComponentMinimum[component] = Math.Min(stats.ComponentMinimum[component], value);
            stats.ComponentMaximum[component] = Math.Max(stats.ComponentMaximum[component], value);
            stats.ComponentSum[component] += value;
        }
        if (!Double.IsNaN(value) && !Double.IsInfinity(value) && Math.Abs(value) < 1.0E19)
        {
            stats.BoundedNumericValues++;
            stats.BoundedMinimum = Math.Min(stats.BoundedMinimum, value);
            stats.BoundedMaximum = Math.Max(stats.BoundedMaximum, value);
            stats.BoundedSum += value;
        }
        if (stats.Samples.Count < 8)
            stats.Samples.Add(value.ToString("R", CultureInfo.InvariantCulture));
    }

    private static void AddBase64Bytes(PathStats stats, string value)
    {
        byte[] bytes;
        try
        {
            bytes = Convert.FromBase64String(value);
        }
        catch (FormatException)
        {
            return;
        }
        stats.BinaryBytes += bytes.Length;
        for (int index = 0; index < bytes.Length; index++)
        {
            int number = bytes[index];
            if (number == 0)
                stats.BinaryZeroBytes++;
            stats.BinaryMinimum = Math.Min(stats.BinaryMinimum, number);
            stats.BinaryMaximum = Math.Max(stats.BinaryMaximum, number);
            stats.BinarySum += number;
        }
    }

    private static string JoinComponents(PathStats stats, Converter<int, string> formatter)
    {
        if (stats.ComponentWidth <= 0)
            return String.Empty;
        List<string> values = new List<string>();
        for (int index = 0; index < stats.ComponentWidth; index++)
            values.Add(stats.ComponentCounts[index] > 0 ? formatter(index) : String.Empty);
        return String.Join(" | ", values.ToArray());
    }

    private static string BuildPath(List<string> names, int depth)
    {
        if (depth < 0)
            return "/";
        return "/" + String.Join("/", names.GetRange(0, Math.Min(depth + 1, names.Count)).ToArray());
    }

    private static string Escape(string value)
    {
        return value.Replace("\t", " ").Replace("\r", " ").Replace("\n", " ");
    }

    private static int ConvertBatch(string assemblyPath, string manifestPath)
    {
        try
        {
            MethodInfo factory = LoadFactory(assemblyPath);
            foreach (string line in File.ReadLines(manifestPath))
            {
                if (String.IsNullOrWhiteSpace(line))
                    continue;
                string[] fields = line.Split(new[] { '\t' }, 2);
                if (fields.Length != 2)
                    throw new InvalidDataException("Invalid bridge manifest row: " + line);
                ConvertFile(factory, fields[0], fields[1]);
            }
            return 0;
        }
        catch (Exception error)
        {
            Console.Error.WriteLine(error);
            return 1;
        }
    }

    private static MethodInfo LoadFactory(string assemblyPath)
    {
        Assembly assembly = Assembly.LoadFrom(Path.GetFullPath(assemblyPath));
        Type readerType = assembly.GetType(
            "Slb.Ocean.Petrel.Data.Persistence.BinaryXmlReader",
            true
        );
        return readerType.GetMethod(
            "CreateXmlReader",
            BindingFlags.Public | BindingFlags.Static
        );
    }

    private static void ConvertFile(MethodInfo factory, string inputPath, string outputPath)
    {
        Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(outputPath)));
        using (FileStream input = File.OpenRead(inputPath))
        using (XmlDictionaryReader reader = (XmlDictionaryReader)factory.Invoke(null, new object[] { input }))
        using (XmlWriter writer = XmlWriter.Create(outputPath, new XmlWriterSettings
        {
            Encoding = new UTF8Encoding(false),
            Indent = true,
            CloseOutput = true
        }))
        {
            writer.WriteNode(reader, true);
        }
    }
}
