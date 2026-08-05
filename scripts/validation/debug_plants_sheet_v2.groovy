@Grab(group='org.apache.poi', module='poi-ooxml', version='5.2.5')
import org.apache.poi.ss.usermodel.*
import org.apache.poi.xssf.usermodel.XSSFWorkbook
import java.io.File

def excelFile = new File("data/metadata/samples/Sample_Mastersheet.xlsx")
FileInputStream fis = new FileInputStream(excelFile)
Workbook workbook = new XSSFWorkbook(fis)
Sheet sheet = workbook.getSheet("Plants")

Row headerRow = sheet.getRow(0)
println "Headers: " + headerRow.collect { "[${it.toString()}]" }.join(" ")

(1..10).each { idx ->
    Row row = sheet.getRow(idx)
    if (row) {
        println "Row ${idx}: " + (0..<headerRow.getLastCellNum()).collect { cIdx -> 
            def cell = row.getCell(cIdx)
            "[${cell?.toString()}]"
        }.join(" ")
    }
}
